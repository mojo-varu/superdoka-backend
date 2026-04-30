#!/bin/bash
# Usage: ./vfm.sh <platform_user_id> "<message>"
curl -s -X POST http://localhost:8000/api/v1/vfm/update \
  -H "Content-Type: application/json" \
  -d "{\"operator_id\": \"$1\", \"chat_id\": \"test_$1\", \"text\": \"$2\", \"source\": \"rest\"}" \
  | python3 -m json.tool
