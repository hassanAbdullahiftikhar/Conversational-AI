# Post Phase 8 Fixes

This document records all fixes and optimizations applied AFTER Phase 8 implementation was completed.

## 1. Calculator Math Clarification

**Issue**: LLM refused to do math saying "math homework is off-topic".

**Root Cause**: Prompt had "math homework" in off-topic list, contradicting the calculator tool existence.

**Fix**: Added explicit exception in prompt_builder.py at line 172:
```
- Mathematical calculations ARE allowed when using the calculator tool - this is part of your explicit toolset.
```

**Status**: ✅ FIXED

## 2. CRM Deadlock Resolution

**Issue**: CRM tools timed out at 30 seconds (100% failure rate).

**Root Cause**: `update_crm_profile_async` held `_CRM_LOCK` then called `get_crm_profile_async` which tried to re-acquire the same non-reentrant lock.

**Fix**: Refactored session_store.py to use direct SQL SELECT inside the lock context instead of calling get function.

**Status**: ✅ FIXED

## 3. Multi-Tool Calling Implementation

**Issue**: Only first tool call was executed; array format `[{}]` was ignored.

**Root Cause**: `_extract_tool_call()` returned on first match only.

**Fix**: 
- Created `_extract_tool_calls()` returning list with array handling
- Created `_render_multi_tool_context()` for token budgeting
- Updated execution loop for sequential tool execution
- Added MAX_MULTI_TOOLS=3 constant

**Status**: ✅ FIXED

## 4. Fallback Trigger (Text+JSON)

**Issue**: LLM output explanatory text before JSON block; tool extraction failed.

**Root Cause**: Tool interception checked if START of text looked like tool call; text prefix caused rejection.

**Fix**: Added `has_json_markers` check in websocket_handler.py - looks for ``` or / in buffer. If JSON markers exist, continue collecting even if `_looks_like_tool_call` returns False.

**Status**: ✅ FIXED

## 5. URL Fetch Description

**Issue**: LLM never used url_fetch tool even when appropriate.

**Root Cause**: Tool description didn't explain when to use it.

**Fix**: Added explicit "Use when:" and "Triggers:" guidance connecting search results to URL fetching.

**Status**: ✅ FIXED

## 6. CRM Domain Exception

**Issue**: LLM refused to save profile data, treated "CRM" as off-topic.

**Root Cause**: No CRM exception in domain boundaries section.

**Fix**: Added in prompt_builder.py:
```
- User profile management IS allowed when using crm_profile_read or crm_profile_write tools - this personalizes your support experience.
```

**Status**: ✅ FIXED

## 7. PROMPT_SLOT_TOOLS_TOKENS (CRITICAL)

**Issue**: CRM tools not visible to LLM; LLM said "I don't have crm_profile_write tool".

**Root Cause**: Token budget was 400 tokens but tools section was ~900 tokens. System silently clipped tool list, cutting off CRM tools (listed last).

**Fix**: Increased PROMPT_SLOT_TOOLS_TOKENS from 400 to 1200 in prompt_builder.py.

**Status**: ✅ FIXED

## 8. Domain Boundary Relaxation

**Issue**: LLM too restrictive - "I only possess tools for smart home automation".

**Root Cause**: "You ONLY answer questions related to... your explicit toolset" was too strong.

**Fix**: 
- Changed "ONLY answer" → "primarily answer"
- Removed "OR your explicit toolset" from domain boundaries
- Simplified decline instruction

**Status**: ✅ FIXED

## 9. Location Field Addition

**Issue**: "I live in Wah Cantt" not saved; only name was persisted.

**Root Cause**: CRM schema had `city` but not `location` field. LLM sent "location" when user said "I live in...".

**Fix**: 
- Added `location: str | None = Field(default=None, max_length=80)` to CRMProfileWriteInput in tool_router.py
- Updated prompt with location in tool arguments list

**Status**: ✅ FIXED

## Summary Table

| Fix # | Issue | Root Cause | Solution | Status |
|-------|-------|----------|---------|--------|
| 1 | Math refused | Prompt contradiction | Added exception line | ✅ |
| 2 | CRM timeout | Deadlock | Direct SQL inside lock | ✅ |
| 3 | One tool only | Single return | _extract_tool_calls() | ✅ |
| 4 | Text+JSON | Text prefix reject | has_json_markers | ✅ |
| 5 | url_fetch unused | No description | Added guidance | ✅ |
| 6 | Profile refused | No exception | Added exception | ✅ |
| 7 | CRM missing | Clipped at 400 | Budget 1200 | ✅ |
| 8 | Too restrictive | "ONLY" rule | Relaxed | ✅ |
| 9 | Location not save | No field | Added field | ✅ |

## Testing Notes

After applying fixes, rebuild Docker stack:
```bash
docker compose down
docker compose build conv-manager
docker compose up -d
```

Test queries:
- "my name is Hammad and I live in Wah Cantt"
- "what does my profile say?"
- "calculate the sum and product of 11 and 12"
- "write a poem about cats" (should decline politely)