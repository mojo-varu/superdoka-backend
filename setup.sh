#!/usr/bin/env bash
set -euo pipefail

BASE="http://localhost:8000/api/v1"

# ---------------------------------------------------------------------------
# Step 0 — Wipe existing data for a clean slate
# ---------------------------------------------------------------------------
echo "=== Step 0: Wiping existing data ==="
curl -s -X DELETE "$BASE/demo/wipe" | python3 -c "import json,sys; print(json.load(sys.stdin))"

# ---------------------------------------------------------------------------
# Step 1 — Register owner
# ---------------------------------------------------------------------------
echo "=== Step 1: Register owner ==="
OWNER_RESP=$(curl -s -X POST "$BASE/owner/register" \
  -H "Content-Type: application/json" \
  -d '{"name": "Алексей Петров", "mobile": "+79801234500", "platform_user_id": 9999}')
echo "$OWNER_RESP"
OWNER_ID=$(echo "$OWNER_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "OWNER_ID=$OWNER_ID"

# ---------------------------------------------------------------------------
# Step 2 — Add machines
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 2: Add machines ==="

MACH_RESP=$(curl -s -X POST "$BASE/owner/machines" \
  -H "Content-Type: application/json" \
  -H "X-Platform-User-Id: 9999" \
  -d '{"reg_number": "А771МР77", "alias": "Экскаватор-1", "machine_type": "Экскаватор", "model": "Caterpillar 320D", "year": 2019, "serial_number": "CAT0320DKXR01234", "notes": "Основной экскаватор, карьер №2"}')
echo "$MACH_RESP"
MACH_EXCAVATOR=$(echo "$MACH_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "MACH_EXCAVATOR=$MACH_EXCAVATOR"

MACH_RESP=$(curl -s -X POST "$BASE/owner/machines" \
  -H "Content-Type: application/json" \
  -H "X-Platform-User-Id: 9999" \
  -d '{"reg_number": "В542КХ77", "alias": "БелАЗ-1", "machine_type": "Самосвал", "model": "БелАЗ 75131", "year": 2020, "notes": "Самосвал, карьер №2"}')
echo "$MACH_RESP"
MACH_DUMPTRUCK=$(echo "$MACH_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "MACH_DUMPTRUCK=$MACH_DUMPTRUCK"

MACH_RESP=$(curl -s -X POST "$BASE/owner/machines" \
  -H "Content-Type: application/json" \
  -H "X-Platform-User-Id: 9999" \
  -d '{"reg_number": "К007МР50", "alias": "Бульдозер-1", "machine_type": "Бульдозер", "model": "Komatsu D155AX", "year": 2018, "notes": "Бульдозер, карьер №2"}')
echo "$MACH_RESP"
MACH_BULLDOZER=$(echo "$MACH_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "MACH_BULLDOZER=$MACH_BULLDOZER"

# ---------------------------------------------------------------------------
# Step 3 — Add operators
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 3: Add operators ==="

OP_RESP=$(curl -s -X POST "$BASE/owner/operators" \
  -H "Content-Type: application/json" \
  -H "X-Platform-User-Id: 9999" \
  -d '{"name": "Иван Сидоров", "mobile": "+79001234501", "platform_user_id": 2001}')
echo "$OP_RESP"
OP_IVAN=$(echo "$OP_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "OP_IVAN=$OP_IVAN"

OP_RESP=$(curl -s -X POST "$BASE/owner/operators" \
  -H "Content-Type: application/json" \
  -H "X-Platform-User-Id: 9999" \
  -d '{"name": "Пётр Кузнецов", "mobile": "+79001234502", "platform_user_id": 2002}')
echo "$OP_RESP"
OP_PETR=$(echo "$OP_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "OP_PETR=$OP_PETR"

OP_RESP=$(curl -s -X POST "$BASE/owner/operators" \
  -H "Content-Type: application/json" \
  -H "X-Platform-User-Id: 9999" \
  -d '{"name": "Михаил Фёдоров", "mobile": "+79001234503", "platform_user_id": 2003}')
echo "$OP_RESP"
OP_MISHA=$(echo "$OP_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "OP_MISHA=$OP_MISHA"

# ---------------------------------------------------------------------------
# Step 4 — Assign operators to machines
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 4: Assignments ==="

echo "Ivan -> Excavator"
curl -s -X POST "$BASE/owner/assignments" \
  -H "Content-Type: application/json" \
  -H "X-Platform-User-Id: 9999" \
  -d "{\"operator_id\": $OP_IVAN, \"machine_id\": $MACH_EXCAVATOR}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('detail', 'ok'))"

echo "Ivan -> Dump truck (backup)"
curl -s -X POST "$BASE/owner/assignments" \
  -H "Content-Type: application/json" \
  -H "X-Platform-User-Id: 9999" \
  -d "{\"operator_id\": $OP_IVAN, \"machine_id\": $MACH_DUMPTRUCK}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('detail', 'ok'))"

echo "Pyotr -> Dump truck"
curl -s -X POST "$BASE/owner/assignments" \
  -H "Content-Type: application/json" \
  -H "X-Platform-User-Id: 9999" \
  -d "{\"operator_id\": $OP_PETR, \"machine_id\": $MACH_DUMPTRUCK}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('detail', 'ok'))"

echo "Mikhail -> Bulldozer"
curl -s -X POST "$BASE/owner/assignments" \
  -H "Content-Type: application/json" \
  -H "X-Platform-User-Id: 9999" \
  -d "{\"operator_id\": $OP_MISHA, \"machine_id\": $MACH_BULLDOZER}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('detail', 'ok'))"

# ---------------------------------------------------------------------------
# Step 5 — Verify fleet and operators
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 5: Fleet summary ==="
curl -s "$BASE/owner/fleet/summary" | python3 -c "
import json, sys
d = json.load(sys.stdin)
machines = d.get('machines', [])
print(f'Total machines: {len(machines)}')
for m in machines:
    print(f'  {m[\"reg_number\"]} ({m.get(\"alias\",\"-\")}) | {m[\"machine_type\"]} | status:{m[\"status\"]}')
"

echo ""
echo "=== Step 5: Operator list ==="
curl -s "$BASE/operator/list" | python3 -c "
import json, sys
ops = json.load(sys.stdin)
for op in ops:
    machines = [m['reg_number'] for m in op.get('machines', [])]
    print(f'  id:{op[\"id\"]} {op[\"name\"]} | platform_id:{op.get(\"platform_user_id\",\"-\")} | machines:{machines}')
"

# ---------------------------------------------------------------------------
# Step 6 — Duplicate registration guard test
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 6: Duplicate reg_number guard (expect 409) ==="
curl -s -X POST "$BASE/owner/machines" \
  -H "Content-Type: application/json" \
  -H "X-Platform-User-Id: 9999" \
  -d '{"reg_number": "А771МР77", "machine_type": "Экскаватор", "model": "Другая модель", "year": 2021}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('detail', d))"

echo ""
echo "=== Done ==="
