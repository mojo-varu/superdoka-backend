# Detailed Code Comparison

## The Core Problem

### Line 321 - Add Operator Function (BROKEN)

**Current Code:**
```python
existing = await db.execute(
    select(User).where(
        and_(
            User.mobile == operator.contact,
            User.owner_id == current_user.id,
            User.user_type == UserTypeEnum.OPERATOR.value  # ❌ ERROR HERE
        )
    )
)
```

**What Happens:**
1. Python encounters `UserTypeEnum` 
2. Python looks for `UserTypeEnum` in current scope
3. Not found ❌
4. Raises `NameError: name 'UserTypeEnum' is not defined`
5. Exception caught by generic except block (line 356)
6. Returns `HTTPException(status_code=500, detail="Internal server error")`

**Fixed Code (Option A - String):**
```python
existing = await db.execute(
    select(User).where(
        and_(
            User.mobile == operator.contact,
            User.owner_id == current_user.id,
            User.user_type == "OPERATOR"  # ✅ FIXED
        )
    )
)
```

**Fixed Code (Option B - Enum):**
```python
existing = await db.execute(
    select(User).where(
        and_(
            User.mobile == operator.contact,
            User.owner_id == current_user.id,
            User.user_type == UserType.OPERATOR.value  # ✅ FIXED (with import)
        )
    )
)
```

---

## Complete List of Affected Lines

### In add_operator() function (Lines 307-358)

**Line 321 - Query check:**
```python
# BROKEN
User.user_type == UserTypeEnum.OPERATOR.value

# FIXED (Option A)
User.user_type == "OPERATOR"

# FIXED (Option B)  
User.user_type == UserType.OPERATOR.value
```

**Line 333 - Create operator:**
```python
# BROKEN
user_type=UserTypeEnum.OPERATOR.value

# FIXED (Option A)
user_type="OPERATOR"

# FIXED (Option B)
user_type=UserType.OPERATOR.value
```

---

### In get_operators() function (Lines 360-375)

**Line 370 - Query:**
```python
# BROKEN
User.user_type == UserTypeEnum.OPERATOR.value

# FIXED (Option A)
User.user_type == "OPERATOR"

# FIXED (Option B)
User.user_type == UserType.OPERATOR.value
```

---

### In assign_operator() function (Lines 377-463)

**Line 405 - Query:**
```python
# BROKEN
User.user_type == UserTypeEnum.OPERATOR.value

# FIXED (Option A)
User.user_type == "OPERATOR"

# FIXED (Option B)
User.user_type == UserType.OPERATOR.value
```

---

### In commented code (Lines 186-239)

**Line 201 - Commented query (same bug):**
```python
# BROKEN
User.user_type == UserTypeEnum.OWNER.value

# FIXED (Option A)
User.user_type == "OWNER"

# FIXED (Option B - with import)
User.user_type == UserType.OWNER.value
```

**Line 213 - Commented create (same bug):**
```python
# BROKEN
user_type=UserTypeEnum.OWNER.value

# FIXED (Option A)
user_type="OWNER"

# FIXED (Option B - with import)
user_type=UserType.OWNER.value
```

---

## Why the Error Happens

1. **No Import:** `UserTypeEnum` is never imported or defined
2. **Wrong Name:** The enum in models.py is called `UserType`, not `UserTypeEnum`
3. **Silent Failure:** The exception is caught by the generic exception handler (line 356-358)
4. **Generic Error:** Returns 500 instead of a specific error message

---

## Recommended Fix: Option A (String Literals)

### Why:
✅ Minimal changes  
✅ No additional imports  
✅ Matches the CheckConstraint in models.py  
✅ Works with database constraints  

### Changes needed:

1. Line 321: `"OPERATOR"` (instead of `UserTypeEnum.OPERATOR.value`)
2. Line 333: `"OPERATOR"` (instead of `UserTypeEnum.OPERATOR.value`)
3. Line 370: `"OPERATOR"` (instead of `UserTypeEnum.OPERATOR.value`)
4. Line 405: `"OPERATOR"` (instead of `UserTypeEnum.OPERATOR.value`)
5. Line 201 (comment): `"OWNER"` (instead of `UserTypeEnum.OWNER.value`)
6. Line 213 (comment): `"OWNER"` (instead of `UserTypeEnum.OWNER.value`)

---

## Alternative: Option B (Enum Import)

### Changes needed:

1. **Update import (Line 15):**
```python
# BEFORE
from app.db.models import User, Machine, MachineAssignment, FuelLog, HoursLog, IssueReport, ActivityLog

# AFTER
from app.db.models import User, Machine, MachineAssignment, FuelLog, HoursLog, IssueReport, ActivityLog, UserType
```

2. Then update all 6 occurrences to use `UserType.OPERATOR.value` and `UserType.OWNER.value`

---

## Verification

The fix is correct when:
- No `NameError` exceptions
- `POST /api/v1/owner/operators` returns 200 (not 500)
- Operator is created in database
- ActivityLog records the action
