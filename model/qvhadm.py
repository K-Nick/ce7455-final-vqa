import torch
import torch.nn as nn
import torch.nn.functional as F
from .peterson_base import ReLUNet


class HadamardAttention(nn.Module):
    def __init__(self, q_dim, v_dim, hidden_size) -> None:
        super().__init__()
        self.qv_proj = nn.Linear(hidden_size, 1)

    def forward(self, q_emb, v_emb):
        q_emb = self.q_proj(q_emb)
        v_emb = self.v_proj(v_emb)
        qv_emb = q_emb * v_emb
        qv_attn = self.qv_proj(qv_emb)

        return qv_attn


class QVHadamard(nn.Module):
    def __init__(self, conf, pre_emb=None) -> None:
        super().__init__()
        q_dim = 300
        v_dim = 2048
        num_hid = 1024
        fa_num_hid = 1280
        dropout = 0.5
        num_ans = conf.data.num_ans

        self.emb = nn.Embedding.from_pretrained(pre_emb, padding_idx=0)
        self.gru = nn.GRU(q_dim, num_hid, batch_first=True, bidirectional=True)

        self.attn_fn = HadamardAttention(2 * num_hid, v_dim, num_hid)

        self.pre_q_proj = ReLUNet(2 * num_hid, num_hid)
        self.pre_v_proj = ReLUNet(v_dim, num_hid)

        self.q_proj = ReLUNet(num_hid, num_hid)
        self.v_proj = ReLUNet(num_hid, num_hid)

        self.clf = nn.Sequential(
            ReLUNet(num_hid, num_hid),
            nn.Dropout(dropout),
            nn.Linear(num_hid, num_ans - 1),
        )
        # self.do = nn.Dropout(p=dropout)
        self.conf = conf

    def forward(self, v_emb, img_spatial, qs, q_lens):
        """detailed model is in https://arxiv.org/pdf/1708.02711.pdf"""
        bsz = qs.shape[0]

        q_emb = self.emb(qs)

        # sentence embedding
        outputs, hn = self.gru(q_emb)
        q_emb = hn.transpose(0, 1).reshape((bsz, -1))

        q_emb = self.pre_q_proj(q_emb)
        v_emb = self.pre_v_proj(v_emb)

        # l2 norm
        # v_emb = v_emb / torch.sqrt(torch.sum(v_emb * v_emb, dim=2, keepdim=True))

        # attention
        attn_score = self.attn_score(v_emb, q_emb)
        v_attn_emb = torch.bmm(attn_score.unsqueeze(1), v_emb).squeeze(1)
        # v_attn_emb = torch.einsum("ijk,ij->ik", v_emb, attn_score)

        # projection
        q_emb = self.q_proj(q_emb)
        v_emb = self.v_proj(v_attn_emb)

        qv_emb = q_emb * v_emb

        # qv_emb = self.dropout(qv_emb)
        logit = self.clf(qv_emb)

        return logit

    def attn_score(self, v_emb, q_emb):
        num_bbox = v_emb.shape[1]
        q_emb = q_emb.unsqueeze(1).repeat((1, num_bbox, 1))
        logit = self.attn_fn(q_emb, v_emb).squeeze(2)

        score = F.softmax(logit, dim=1)

        return score
