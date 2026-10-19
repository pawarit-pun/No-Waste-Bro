"""การแจกแจง Negative Binomial แบบ mean / dispersion ใช้หาโอกาสขายหมดและช่วง low-high

ยอดขายรายวันผันผวนมากกว่า Poisson (variance = phi x mean, phi > 1) จึงใช้ NB
ผลรวมหลายวันใช้ mean รวม และ variance รวม = phi x mean รวม (ถือว่าแต่ละวันอิสระกัน)
"""
import math


def _params(mean, phi):
    phi = max(phi, 1.0 + 1e-6)
    r = mean / (phi - 1.0)
    p = r / (r + mean)
    return r, p


def pmf_list(mean, phi, upto):
    """ความน่าจะเป็น P(X = k) สำหรับ k = 0..upto"""
    if mean <= 0:
        return [1.0] + [0.0] * upto
    r, p = _params(mean, phi)
    log_p, log_q = math.log(p), math.log(1.0 - p)
    base = r * log_p - math.lgamma(r)
    return [math.exp(base + math.lgamma(k + r) - math.lgamma(k + 1) + k * log_q) for k in range(upto + 1)]


def prob_at_least(q, mean, phi):
    """P(X >= q): โอกาสที่ความต้องการถึง q หน่วย (= ขายหมด lot ขนาด q)"""
    if q <= 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - sum(pmf_list(mean, phi, int(q) - 1))))


def quantile(prob, mean, phi, cap=None):
    """ค่า k ที่น้อยที่สุดที่ P(X <= k) >= prob (ตัดไม่เกิน cap)"""
    if mean <= 0:
        return 0
    limit = int(mean * 6 + 30)
    acc = 0.0
    for k, v in enumerate(pmf_list(mean, phi, limit)):
        acc += v
        if acc >= prob:
            return k if cap is None else min(k, cap)
    return limit if cap is None else min(limit, cap)
