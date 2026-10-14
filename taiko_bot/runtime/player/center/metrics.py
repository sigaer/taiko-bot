from sakura_taiko_core.rating.v1 import build_const_table, calc_accuracy, calc_y, compute_AI, compute_P, compute_Q, lookup_const_score
from sakura_taiko_core.dimension.v1 import compute_AD_AE_AF_AG, compute_six_dims
from sakura_taiko_core.rating import v2 as domain_v2
def _calculate_v2_from_chart(chart, *, accuracy_per, bad_per):
    return domain_v2._calculate_v2_from_chart(chart, accuracy_per=accuracy_per, bad_per=bad_per,
        profile="v2-center-20261010")
