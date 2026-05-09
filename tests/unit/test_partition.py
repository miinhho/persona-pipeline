import polars as pl

from persona_pipeline.mappings import (
    AGE_GEN, OCCUPATION_GROUP, SEGMENT_ID, SEGMENT_KEY, SEGMENT_SEP, SEX,
    get_mappings,
)
from persona_pipeline.stages.partition import partition

SEP = SEGMENT_SEP
KOREA = get_mappings("Korea")
SINGAPORE = get_mappings("Singapore")


def _write_korea(tmp_path, segment_keys: list[str]):
    df = pl.DataFrame({
        "region": [k.split(SEP)[0] for k in segment_keys],
        "age_gen": [k.split(SEP)[1] for k in segment_keys],
        "sex": [k.split(SEP)[2] for k in segment_keys],
        "occupation_group": [k.split(SEP)[3] for k in segment_keys],
        SEGMENT_KEY: segment_keys,
    })
    p = tmp_path / "in.parquet"
    df.write_parquet(p)
    return p


def _run(tmp_path, in_path, mapping, min_size):
    out = tmp_path / "out.parquet"
    partition(in_path, out, mapping, min_size=min_size)
    return pl.read_parquet(out)


def test_row_count_preserved_and_no_null_segment_id(tmp_path):
    keys = [f"수도권{SEP}청년{SEP}남자{SEP}전문가"] * 50 + [f"영남권{SEP}노년{SEP}여자{SEP}단순노무"] * 50
    out = _run(tmp_path, _write_korea(tmp_path, keys), KOREA, min_size=10)
    assert len(out) == 100
    assert out[SEGMENT_ID].null_count() == 0


def test_l0_kept_when_all_segments_large_enough(tmp_path):
    keys = [f"수도권{SEP}청년{SEP}남자{SEP}전문가"] * 100 + [f"영남권{SEP}노년{SEP}여자{SEP}단순노무"] * 100
    out = _run(tmp_path, _write_korea(tmp_path, keys), KOREA, min_size=50)
    assert set(out[SEGMENT_ID].to_list()) == {
        f"수도권{SEP}청년{SEP}남자{SEP}전문가",
        f"영남권{SEP}노년{SEP}여자{SEP}단순노무",
    }


def test_per_segment_only_small_segment_backs_off(tmp_path):
    # 80짜리는 자기 자신 유지, 30짜리만 backoff (b1 잔여 30 < 50 → b2로 cascade).
    keys = [f"수도권{SEP}청년{SEP}남자{SEP}전문가"] * 30 + [f"수도권{SEP}청년{SEP}남자{SEP}사무"] * 80
    out = _run(tmp_path, _write_korea(tmp_path, keys), KOREA, min_size=50)
    ids = set(out[SEGMENT_ID].to_list())
    assert f"수도권{SEP}청년{SEP}남자{SEP}사무" in ids  # 큰 L0는 자기 자신
    assert f"청년{SEP}남자" in ids                       # 작은 L0는 b2까지 cascade


def test_l1_backoff_when_residual_meets_min_size(tmp_path):
    # 같은 b1 안에서 작은 L0 두 개의 합이 min_size를 넘으면 b1까지만 backoff.
    keys = (
        [f"수도권{SEP}청년{SEP}남자{SEP}전문가"] * 30
        + [f"수도권{SEP}청년{SEP}남자{SEP}사무"] * 30
    )
    out = _run(tmp_path, _write_korea(tmp_path, keys), KOREA, min_size=50)
    assert out[SEGMENT_ID].n_unique() == 1
    assert out[SEGMENT_ID][0] == f"수도권{SEP}청년{SEP}남자"


def test_l2_backoff_drops_first_and_last_axes(tmp_path):
    keys = (
        [f"수도권{SEP}청년{SEP}남자{SEP}전문가"] * 5
        + [f"영남권{SEP}청년{SEP}남자{SEP}사무"] * 5
        + [f"호남권{SEP}청년{SEP}남자{SEP}서비스"] * 5
    )
    out = _run(tmp_path, _write_korea(tmp_path, keys), KOREA, min_size=10)
    assert out[SEGMENT_ID].n_unique() == 1
    assert out[SEGMENT_ID][0] == f"청년{SEP}남자"


def test_3_axes_country_per_segment_cascade(tmp_path):
    # 80짜리는 자기 자신 유지, 20짜리는 b1 잔여 20 < 50 → b2 (= [SEX]) "Male"로 cascade.
    keys = [f"young{SEP}Male{SEP}Professional"] * 20 + [f"young{SEP}Male{SEP}Manager"] * 80
    df = pl.DataFrame({
        AGE_GEN: [k.split(SEP)[0] for k in keys],
        SEX: [k.split(SEP)[1] for k in keys],
        OCCUPATION_GROUP: [k.split(SEP)[2] for k in keys],
        SEGMENT_KEY: keys,
    })
    p = tmp_path / "sg.parquet"
    df.write_parquet(p)
    out = _run(tmp_path, p, SINGAPORE, min_size=50)
    ids = set(out[SEGMENT_ID].to_list())
    assert f"young{SEP}Male{SEP}Manager" in ids
    assert "Male" in ids
