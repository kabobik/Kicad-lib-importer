"""Extract physical copper groups using KiCad, and patch only PCB net fields."""
from __future__ import annotations

import hashlib
from pathlib import Path

from tools.kicad_sexpr import edit, parse, quote

FORMAT = 'kicad-copper-connectivity-v1'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def uid(item):
    return item.m_Uuid.AsString()


def extract(path: Path, prefix='REC') -> dict:
    import pcbnew

    source = path.read_bytes()
    board = pcbnew.LoadBoard(str(path))
    if board is None:
        raise ValueError(f'Cannot read PCB: {path}')
    footprints = list(board.GetFootprints())
    pads = [p for f in footprints for p in f.Pads() if p.IsOnCopperLayer()]
    items = pads + list(board.GetTracks())
    zones = [z for z in board.Zones() if z.IsOnCopperLayer() and not z.GetIsRuleArea()]
    drawings = (list(board.GetDrawings()) + [g for f in footprints for g in f.GraphicalItems()]
                + [field for f in footprints for field in f.GetFields()])
    conductive_drawing_types = {pcbnew.PCB_SHAPE_T, pcbnew.PCB_TEXT_T, pcbnew.PCB_TEXTBOX_T, pcbnew.PCB_FIELD_T}
    unsupported = [uid(g) for g in drawings
                   if g.Type() in conductive_drawing_types and g.IsOnCopperLayer()
                   and (not hasattr(g, 'IsVisible') or g.IsVisible())]
    if unsupported:
        raise ValueError('Copper graphics/text are not handled by KiCad connectivity; '
                         'convert them to pads/tracks/zones first: ' + ', '.join(unsupported[:10]))
    if any(not z.IsFilled() for z in zones):
        raise ValueError('PCB contains unfilled copper zones. Save the intended fills first; '
                         'recovery never refills zones.')
    by_id = {uid(item): item for item in items}
    if len(by_id) != len(items):
        raise ValueError('Duplicate PCB object UUIDs')
    pin_by_id = {}
    refs = [f.GetReference() for f in footprints]
    if len(refs) != len(set(refs)) or any(not ref or '?' in ref for ref in refs):
        raise ValueError('PCB references must be unique and annotated')
    for pad in pads:
        if pad.GetNumber():
            footprint = pad.GetParentFootprint()
            ref, number = footprint.GetReference(), pad.GetNumber()
            pin_by_id[uid(pad)] = {
                'ref': ref, 'pin': number, 'key': ref + '.' + number,
                'pad_uuid': uid(pad), 'symbol_path': footprint.GetPath().AsString(),
            }
    old_names = {uid(item): item.GetNetname() for item in items + zones}
    # Net assignments must not filter zone/pad contacts. Only the in-memory board
    # is normalized. Cached polygons, object geometry, and the source file stay intact.
    neutral = pcbnew.NETINFO_ITEM(board, '__copper_recovery__')
    board.Add(neutral)
    for item in items + zones:
        item.SetNetCode(neutral.GetNetCode())
    connectivity = board.GetConnectivity()
    if not connectivity.Build(board):
        raise ValueError('KiCad could not build PCB connectivity')
    groups = []
    object_groups = []
    if items and not zones:
        # Initialize native contact search once, then walk its direct neighbours.
        # Unlike GetConnectedItems per net, this avoids rescanning every cluster
        # for each isolated pad on large zone-free boards.
        connectivity.GetConnectedItems(items[0], pcbnew.IGNORE_NETS)
        parent = {key: key for key in by_id}

        def find(key):
            while parent[key] != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key

        for item_id, item in by_id.items():
            for other in list(connectivity.GetConnectedPads(item)) + list(connectivity.GetConnectedTracks(item)):
                parent[find(uid(other))] = find(item_id)
        buckets = {}
        for item_id in by_id:
            buckets.setdefault(find(item_id), set()).add(item_id)
        object_groups = list(buckets.values())
    else:
        visited = set()
        # Query once per physical group, not once per pad. Never mark an entire
        # ZONE visited: disconnected fill islands can belong to different groups.
        for item_id in sorted(by_id):
            if item_id in visited:
                continue
            connected = connectivity.GetConnectedItems(by_id[item_id], pcbnew.IGNORE_NETS)
            objects = {uid(item) for item in connected} | {item_id}
            members = objects & by_id.keys()
            if members & visited:
                raise ValueError('KiCad returned overlapping physical groups; manual inspection required')
            visited.update(members)
            object_groups.append(objects)
    for objects in object_groups:
        members = objects & by_id.keys()
        pin_rows = [pin_by_id[k] for k in sorted(members) if k in pin_by_id]
        group_id = 'copper-' + digest('\n'.join(sorted(members)).encode())[:16]
        groups.append({
            'id': group_id, 'objects': sorted(objects),
            'pins': sorted(pin_rows, key=lambda p: (p['ref'], p['pin'], p['pad_uuid'])),
            'previous_names': sorted({old_names[k] for k in objects if old_names.get(k)}),
        })
    groups.sort(key=lambda g: ([p['key'] for p in g['pins']], g['id']))
    for i, group in enumerate(groups, 1):
        group['name'] = f'{prefix}{i:02d}'
    return {
        'format': FORMAT, 'source': str(path.resolve()), 'source_sha256': digest(source),
        'kicad_version': pcbnew.GetBuildVersion(),
        'method': 'native connectivity with net assignments neutralized in memory',
        'zone_policy': 'saved fills only; no refill; zone islands remain separate',
        'groups': groups,
        'warnings': [f'{len(pads) - len(pin_by_id)} copper pads have no number']
                    if len(pads) != len(pin_by_id) else [],
    }


def validate_table(table: dict, path: Path, *, require_source_hash=True):
    if table.get('format') != FORMAT:
        raise ValueError('Unsupported connectivity file format')
    if require_source_hash and digest(path.read_bytes()) != table.get('source_sha256'):
        raise ValueError('PCB changed since extraction; run extract again')
    actual = extract(path)
    expected = {g['id']: (g['objects'], g['pins']) for g in actual['groups']}
    supplied = {g['id']: (g['objects'], g['pins']) for g in table['groups']}
    if supplied != expected or len(supplied) != len(table['groups']):
        raise ValueError('Physical groups were edited. Only group names may be changed.')
    names = [g['name'] for g in table['groups']]
    if len(names) != len(set(names)) or any(not isinstance(n, str) or not n.strip() for n in names):
        raise ValueError('Group names must be nonempty and unique')


def physical_signature(table):
    return sorted(tuple(g['objects']) for g in table['groups'])


class NetAssignmentConflict(ValueError):
    """One PCB object cannot carry the separate physical groups' net names."""


def assign_nets(text: str, table: dict, names: dict[str, str]) -> str:
    root = parse(text)
    if root.tag != 'kicad_pcb':
        raise ValueError('Not a KiCad PCB')
    assignments = {}
    for group in table['groups']:
        name = names[group['id']]
        for object_id in group['objects']:
            previous = assignments.setdefault(object_id, name)
            if previous != name:
                raise NetAssignmentConflict('A zone has disconnected islands belonging to different nets. '
                                 f'Split the zone before assigning PCB nets: {object_id}')
    numeric = int(root.value('version', '0')) < 20250000
    definitions = root.all('net')
    if definitions:
        numeric = len(definitions[0].atoms) >= 3
    codes = {n.atoms[2]: int(n.atoms[1]) for n in definitions if len(n.atoms) >= 3}
    codes.setdefault('', 0)
    changes = []
    if numeric:
        next_code = max(codes.values(), default=0) + 1
        added = []
        for name in sorted(set(assignments.values())):
            if name not in codes:
                codes[name] = next_code
                next_code += 1
                added.append(f'(net {codes[name]} {quote(name)})\n\t')
        location = min((n.start for n in root.children if n.tag in ('footprint', 'segment', 'via', 'zone')), default=root.end - 1)
        changes.append((location, location, ''.join(added)))
    nodes = list(root.children)
    for footprint in root.all('footprint'):
        nodes.extend(footprint.all('pad'))
    changed = set()
    for node in nodes:
        object_id = node.value('uuid', node.value('tstamp'))
        if object_id not in assignments:
            continue
        if node.tag not in ('pad', 'segment', 'arc', 'via', 'zone'):
            raise ValueError(f'Unsupported connected PCB object: {node.tag}')
        name = assignments[object_id]
        if numeric:
            net = f'(net {codes[name]}' + (f' {quote(name)}' if node.tag == 'pad' else '') + ')'
        else:
            net = f'(net {quote(name)})'
        if node.all('net'):
            old = node.one('net')
            changes.append((old.start, old.end, net))
        else:
            changes.append((node.end - 1, node.end - 1, '\n\t\t' + net + '\n\t'))
        if numeric and node.tag == 'zone':
            if node.all('net_name'):
                old = node.one('net_name')
                changes.append((old.start, old.end, f'(net_name {quote(name)})'))
            else:
                changes.append((node.end - 1, node.end - 1, f'\n(net_name {quote(name)})\n'))
        changed.add(object_id)
    if changed != assignments.keys():
        raise ValueError('Some connected PCB objects could not be located by UUID')
    return edit(text, changes)


def sync_editor_net_assignments(board, saved_path):
    """Reflect the installed net fields in the open editor, without saving geometry."""
    import pcbnew

    # LoadBoard(active_project_path) returns PCB Editor's existing BOARD even
    # when the file has changed. Use the native file reader for a detached copy.
    saved = pcbnew.PCB_IO_MGR.Load(pcbnew.PCB_IO_MGR.KICAD_SEXP, str(saved_path))
    if saved is None:
        raise ValueError('Cannot reload saved PCB net assignments')

    def objects(value):
        return {uid(item): item for item in
                [p for f in value.GetFootprints() for p in f.Pads()]
                + list(value.GetTracks()) + list(value.Zones())}

    target, source = objects(board), objects(saved)
    if target.keys() != source.keys():
        raise ValueError('Open PCB objects differ from the saved recovery result; reopen the board')
    previous = {key: item.GetNet() for key, item in target.items()}
    added = []
    try:
        nets = {'': board.FindNet(0)}
        for name in sorted({item.GetNetname() for item in source.values()} - {''}):
            net = board.FindNet(name)
            if net is None:
                net = pcbnew.NETINFO_ITEM(board, name)
                board.Add(net)
                added.append(net)
            nets[name] = net
        for key, item in target.items():
            item.SetNet(nets[source[key].GetNetname()])
        if not board.BuildConnectivity():
            raise ValueError('Cannot refresh editor connectivity')
        if any(item.GetNetname() != source[key].GetNetname() for key, item in target.items()):
            raise ValueError('Editor net assignments differ from the saved recovery result')
    except Exception:
        for key, item in target.items():
            item.SetNet(previous[key])
        for net in reversed(added):
            board.Remove(net)
        board.BuildConnectivity()
        raise
