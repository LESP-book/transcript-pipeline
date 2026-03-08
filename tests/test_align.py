from __future__ import annotations

from pathlib import Path

import pytest

from src.align_utils import (
    AlignedBlock,
    AsrBlock,
    AlignmentInputEmptyError,
    ReferenceBlock,
    align_blocks,
    build_alignment_output_path,
    build_asr_blocks,
    build_reference_blocks,
    calculate_average_best_score,
    determine_match_status,
    match_paired_files,
    normalize_text_for_matching,
    split_reference_text,
    write_alignment_result,
)
from src.config_loader import load_settings
from tests.helpers import write_minimal_settings


def test_align_batch_raises_when_asr_dir_empty(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    (tmp_path / "data/intermediate/asr").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/intermediate/extracted_text").mkdir(parents=True, exist_ok=True)

    loaded_settings = load_settings(project_root=tmp_path)

    from src.align_utils import align_batch

    with pytest.raises(AlignmentInputEmptyError):
        align_batch(loaded_settings)


def test_match_paired_files_uses_basename(tmp_path: Path) -> None:
    asr_files = [tmp_path / "session01.json", tmp_path / "session02.json"]
    reference_files = [tmp_path / "session01.txt"]

    pairs = match_paired_files(asr_files, reference_files)

    assert pairs[0].reference_txt_path == tmp_path / "session01.txt"
    assert pairs[1].reference_txt_path is None


def test_build_asr_blocks_merges_segments_by_limits(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path, segmentation_overrides={"max_seconds_per_block": 5})
    loaded_settings = load_settings(project_root=tmp_path)
    segments = [
        {"id": 1, "start": 0.0, "end": 2.0, "text": "第一句"},
        {"id": 2, "start": 2.0, "end": 4.0, "text": "第二句"},
        {"id": 3, "start": 4.0, "end": 40.0, "text": "第三句"},
    ]

    blocks = build_asr_blocks(segments, loaded_settings)

    assert len(blocks) == 2
    assert blocks[0].source_segment_ids == [1, 2]
    assert blocks[1].source_segment_ids == [3]


def test_build_reference_blocks_splits_on_empty_line_and_punctuation(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path, segmentation_overrides={"min_chars_per_block": 1, "max_chars_per_block": 12})
    loaded_settings = load_settings(project_root=tmp_path)
    text = "第一段第一句。第一段第二句；第一段第三句。\n\n标题\n\n第二段很长很长。第二段继续。"

    blocks = build_reference_blocks(text, loaded_settings)

    assert len(blocks) >= 4
    assert blocks[0].reference_text == "第一段第一句。"
    assert any(block.reference_text == "标题" for block in blocks)


def test_split_reference_text_keeps_poem_structure_as_multiple_blocks(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)
    text = (
        "水调歌头•重上井冈山\n"
        "久有凌云志，重上井冈山。千里来寻故地，旧貌变新颜。到处莺歌燕舞，更有潺潺流水，高路入云端。过了黄洋界，险处不须看。\n\n"
        "风雷动，旌旗奋，是人寰。三十八年过去，弹指一挥间。可上九天揽月，可下五洋捉鳖，谈笑凯歌还。世上无难事，只要肯登攀。\n"
    )

    blocks = split_reference_text(text, loaded_settings)

    assert len(blocks) > 3
    assert blocks[0] == "水调歌头•重上井冈山"
    assert blocks[1] == "久有凌云志，重上井冈山。"
    assert blocks[2] == "千里来寻故地，旧貌变新颜。"
    assert blocks[-1] == "世上无难事，只要肯登攀。"


def test_normalize_text_for_matching_unifies_spaces_symbols_and_width() -> None:
    text = "２０２４ 年 • 读书会，第一讲。"

    normalized = normalize_text_for_matching(text)

    assert normalized == "2024年.读书会第一讲"


def test_determine_match_status_uses_thresholds(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    assert determine_match_status(85.0, loaded_settings) == "matched"
    assert determine_match_status(60.0, loaded_settings) == "weak_match"
    assert determine_match_status(20.0, loaded_settings) == "no_match"


def test_align_blocks_outputs_top_k_sorted_candidates(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path, alignment_overrides={"top_k": 2}, segmentation_overrides={"min_chars_per_block": 1})
    loaded_settings = load_settings(project_root=tmp_path)
    asr_blocks = [AsrBlock(block_id=1, source_segment_ids=[1], start=0.0, end=1.0, asr_text="读书会第一讲")]
    reference_blocks = [
        ReferenceBlock(ref_block_id=1, reference_text="完全无关的句子"),
        ReferenceBlock(ref_block_id=2, reference_text="读书会第一讲"),
        ReferenceBlock(ref_block_id=3, reference_text="读书会第一讲扩展版"),
    ]

    aligned_blocks = align_blocks(asr_blocks, reference_blocks, loaded_settings)

    assert len(aligned_blocks[0].top_matches) == 2
    assert aligned_blocks[0].top_matches[0].score >= aligned_blocks[0].top_matches[1].score
    assert aligned_blocks[0].matched_reference_text == "读书会第一讲"


def test_align_batch_uses_real_reference_blocks_in_output(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)
    asr_dir = tmp_path / "data/intermediate/asr"
    reference_dir = tmp_path / "data/intermediate/extracted_text"
    asr_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)

    asr_payload = {
        "segments": [
            {"id": 1, "start": 0.0, "end": 2.0, "text": "久有凌云志重上井冈山"},
            {"id": 2, "start": 2.0, "end": 4.0, "text": "风雷动旌旗奋是人寰"},
        ]
    }
    (asr_dir / "poem.json").write_text(__import__("json").dumps(asr_payload, ensure_ascii=False), encoding="utf-8")
    reference_text = (
        "水调歌头•重上井冈山\n"
        "久有凌云志，重上井冈山。千里来寻故地，旧貌变新颜。到处莺歌燕舞，更有潺潺流水，高路入云端。过了黄洋界，险处不须看。\n\n"
        "风雷动，旌旗奋，是人寰。三十八年过去，弹指一挥间。可上九天揽月，可下五洋捉鳖，谈笑凯歌还。世上无难事，只要肯登攀。\n"
    )
    (reference_dir / "poem.txt").write_text(reference_text, encoding="utf-8")

    from src.align_utils import align_batch
    summary = align_batch(loaded_settings)
    assert summary.success == 1

    output_path = tmp_path / "data/intermediate/aligned/poem.json"
    payload = __import__("json").loads(output_path.read_text(encoding="utf-8"))

    split_blocks = split_reference_text(reference_text, loaded_settings)
    assert payload["total_reference_blocks"] == len(split_blocks)
    assert payload["total_reference_blocks"] > 3
    assert len(payload["blocks"][0]["top_matches"]) > 1


def test_write_alignment_result_keeps_output_structure_compatible(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)
    output_dir = tmp_path / "data/intermediate/aligned"
    output_path = build_alignment_output_path(tmp_path / "demo.json", output_dir)
    aligned_blocks = [
        AlignedBlock(
            block_id=1,
            source_segment_ids=[1, 2],
            start=0.0,
            end=3.0,
            asr_text="原始 ASR 文本",
            matched_reference_text="参考文本",
            match_score=88.0,
            match_status="matched",
            top_matches=[],
        )
    ]
    reference_blocks = [ReferenceBlock(ref_block_id=1, reference_text="参考文本")]
    asr_json_path = tmp_path / "data/intermediate/asr/demo.json"
    reference_txt_path = tmp_path / "data/intermediate/extracted_text/demo.txt"
    asr_json_path.parent.mkdir(parents=True, exist_ok=True)
    reference_txt_path.parent.mkdir(parents=True, exist_ok=True)
    asr_json_path.write_text("{}", encoding="utf-8")
    reference_txt_path.write_text("参考文本", encoding="utf-8")

    write_alignment_result(
        asr_json_path=asr_json_path,
        reference_txt_path=reference_txt_path,
        aligned_blocks=aligned_blocks,
        reference_blocks=reference_blocks,
        output_path=output_path,
        loaded_settings=loaded_settings,
    )

    payload = output_path.json_path.read_text(encoding="utf-8")

    assert '"source_asr_file"' in payload
    assert '"source_reference_file"' in payload
    assert '"blocks"' in payload
    assert '"top_matches"' in payload


def test_build_alignment_output_path_uses_asr_basename(tmp_path: Path) -> None:
    asr_json_path = tmp_path / "lecture-01.json"
    output_dir = tmp_path / "data/intermediate/aligned"

    output_path = build_alignment_output_path(asr_json_path, output_dir)

    assert output_path.json_path == output_dir / "lecture-01.json"


def test_calculate_average_best_score_returns_mean() -> None:
    aligned_blocks = [
        AlignedBlock(1, [1], 0.0, 1.0, "a", "b", 80.0, "matched", []),
        AlignedBlock(2, [2], 1.0, 2.0, "c", "d", 60.0, "weak_match", []),
    ]

    assert calculate_average_best_score(aligned_blocks) == 70.0
