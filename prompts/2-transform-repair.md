# Role & Objective
You are an expert code repair agent. Your task is to repair the transformed C++ program so that it preserves the standardized callable interface and resolves the reported verification issue.

# Input
## Current transformed code

{transform_code}

## Verification message

{message}

# Repair Requirements
1. Preserve the standardized public interface:
`void solve(original_input_1, original_input_2, ..., int Global_SF_N, ResultType& Global_Result);`
2. Keep exactly one public external `void solve(...)`.
3. Keep `Global_SF_N` and `Global_Result` unchanged in name and role.
4. Remove any `main` function and execution scaffolding.
5. Preserve the original algorithmic intent as much as possible.
6. Fix the issue indicated by the verification message.
7. Make the final code valid compilable C++.
8. Avoid non-standard shortcuts such as `bits/stdc++.h`; include the standard headers you actually need.
9. Return only the repaired code in a single markdown code block.

# Output Format
You MUST output ONLY the repaired code wrapped in a standard markdown code block.
Do NOT output any explanation or extra text.
