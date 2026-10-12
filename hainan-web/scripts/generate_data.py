"""Regenerate from unsplit roads, validate, then publish a complete web snapshot."""
import argparse
import fcntl
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile

from prepare_data import ROOT, OUT, prepare
from identifiers import assign_ids
from link_splitting import SplitConfig, split_links, validate_split_result
from split_links import read_features, write_json, write_mapping_csv
from osm_topology import extract_node_index, junction_cuts, build_topology
from source_edits import apply_edit, effective_sources, preferred_cuts, read_edits


MIN_LENGTH_M = 100
MAX_LENGTH_M = 10000


def validate_length(value):
    value = float(value)
    if not MIN_LENGTH_M <= value <= MAX_LENGTH_M:
        raise ValueError(f'最大长度需在 {MIN_LENGTH_M}–{MAX_LENGTH_M} m 之间')
    return value


def regenerate(max_length, edit_operation=None, publish=True):
    max_length = validate_length(max_length)
    output_root = ROOT / 'outputs'
    output_root.mkdir(exist_ok=True)
    with (output_root / '.web-generation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('另一个本地服务正在生成路网，请等待完成') from exc
        return _regenerate(max_length, output_root, edit_operation, publish)


def _regenerate(max_length, output_root, edit_operation=None, publish=True):
    with tempfile.TemporaryDirectory(prefix='.web-generation-', dir=output_root) as temporary:
        stage = Path(temporary)
        ids = stage / 'identifiers'
        ids.mkdir()
        registry = ROOT / 'outputs/identifiers/link_id_registry.json'
        if registry.exists():
            shutil.copy2(registry, ids / registry.name)
        # Seed legacy geometry before using the same split ordinal with different boundaries.
        baseline = ROOT / 'outputs/hainan/split'
        original_split = json.loads((baseline / 'links.geojson').read_text())
        original_relations = json.loads((baseline / 'link_relationships.json').read_text())
        assign_ids(original_split['features'], original_relations, ids / registry.name)

        print(f'正在按 {max_length:g} m 切分原始路网…', flush=True)
        collection, _ = read_features(ROOT / 'outputs/hainan/source/hainan_roads.geojson')
        edits_path = ROOT / 'outputs/hainan/edits/source_overrides.json'
        edits = read_edits(edits_path)
        current_snapshot = OUT / 'hainan.json'
        previous = json.loads(current_snapshot.read_text(encoding='utf-8')) if current_snapshot.exists() else {}
        previous_roads = previous.get('roads', [])
        changed_lineage = None
        if edit_operation is not None:
            edits, changed_lineage = apply_edit(collection, edits, edit_operation, previous_roads)
        features = effective_sources(collection, edits)
        config = SplitConfig(max_link_length=max_length)
        node_index = extract_node_index(ROOT / 'data/pbf/hainan-260922.osm.pbf', features)
        same_limit = float(previous.get('generation', {}).get('maxLinkLengthM', -1)) == max_length
        edited_lineages = {f['properties'].get('source_lineage_id') or f['properties']['link_id']
                           for f in features if f['properties'].get('manual_edit')}
        if changed_lineage:
            edited_lineages.add(changed_lineage)
        preferred = preferred_cuts(features, previous_roads, edited_lineages) if same_limit and edited_lineages else {}
        result = split_links(features, config=config, forced_split_points_by_link=junction_cuts(features, node_index),
                             preferred_split_points_by_link=preferred)
        result.relationships, topology_report = build_topology(result.features, node_index)
        if not topology_report['valid']:
            raise ValueError('拓扑校验失败：仍有共享 OSM 节点未切分')
        report = validate_split_result(features, result, config)
        if not report.valid:
            raise ValueError('拆分校验失败：' + '；'.join(report.errors[:5]))
        split_dir = stage / 'split'
        collection['features'] = result.features
        collection['linkSplit'] = {'maxLinkLengthM': max_length, 'snapToleranceM': config.snap_tolerance_m,
                                   'minSegmentLengthM': config.min_segment_length_m}
        generation = {'generatedAt': datetime.now(timezone.utc).isoformat(), 'mode': 'local',
                      'sourceLinks': len(features), 'editRevision': edits['revision']}
        collection['generation'] = generation
        write_json(split_dir / 'links.geojson', collection)
        write_json(split_dir / 'link_relationships.json', result.relationships)
        write_json(split_dir / 'link_mapping.json', result.mapping)
        write_mapping_csv(split_dir / 'link_mapping.csv', result.mapping)
        write_json(split_dir / 'validation_report.json', report.as_dict())
        write_json(split_dir / 'topology_report.json', topology_report)
        print('切分校验通过，正在重建编号与接口关联…', flush=True)
        payload = prepare(split_dir, stage / 'web', ids, stage / 'associations', generation,
                          node_index=node_index, previous_roads=previous_roads)
        if not publish:
            print(f"试算通过：{len(payload['roads']):,} 条路链，未更改已有快照", flush=True)
            return payload
        # Publish only after the complete pipeline succeeds. hainan.json is the commit point.
        print('正在发布完整数据快照…', flush=True)
        destinations = [(split_dir, ROOT / 'outputs/hainan/generated'),
                        (ids, ROOT / 'outputs/identifiers'),
                        (stage / 'associations', ROOT / 'outputs/associations'),
                        (stage / 'web', OUT)]
        if edit_operation is not None:
            edit_stage = stage / 'edits'
            write_json(edit_stage / 'source_overrides.json', edits)
            destinations.insert(-1, (edit_stage, edits_path.parent))
        for directory, destination in destinations:
            destination.mkdir(parents=True, exist_ok=True)
            for path in sorted(directory.iterdir(), key=lambda p: p.name == 'hainan.json'):
                temp = destination / (path.name + '.tmp')
                shutil.copy2(path, temp)
                temp.replace(destination / path.name)
        print(f"已生成 {len(payload['roads']):,} 条路链，最大长度 {max_length:g} m", flush=True)
        return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-link-length', required=True, type=float)
    parser.add_argument('--edit-stdin', action='store_true', help='Read a single local edit operation as JSON from stdin')
    parser.add_argument('--dry-run', action='store_true', help='Validate without publishing source edits or snapshots')
    args = parser.parse_args()
    try:
        operation = json.load(sys.stdin) if args.edit_stdin else None
        regenerate(args.max_link_length, operation, publish=not args.dry_run)
    except Exception as exc:
        print(f'生成失败：{exc}', file=sys.stderr)
        raise SystemExit(1)
