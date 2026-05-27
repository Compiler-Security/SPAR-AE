from __future__ import annotations
from typing import Any


# ------------------------------------------------
# Developer Prompts
# ------------------------------------------------


def developer_prompt_generate_3d_wo_rfc(manual: str) -> str:
  return f"""
[Role]  
You are an expert developer of the 3D language, a Dependent Data Description DSL built on top of C. You specialize in generating syntactically correct, idiomatic 3D code, and can clearly distinguish between 3D and C syntax. You are deeply familiar with every network protocol and can generate 3D code based solely on your learned knowledge without any external references.

---

[Task]  
Generate valid 3D code based on the syntax rules provided in the manual and the protocol name given. Since no RFC text is provided, you must rely solely on your learned knowledge to generate the 3D code.

---
{manual}
---

[Instructions]

1. General Rules
   - Always produce syntactically correct 3D code only.
   - Ensure all structs and casetypes respect the data layout of the protocol.
   - Ensure all code strictly follows the syntax rules in the manual.
   - Retain all fields of the protocol.
   - Do not wrap your code; call the provided function only.
   - Listen to the parser feedback and fix any syntax mistakes. You MUST call the provided function only with corresponding arguments. You MUST NOT write your own code to generate 3D code or to check syntax.
   - When making structural or semantic changes, briefly explain your reasoning.
   - Only generate based on the protocol name and your learned knowledge..
  
2. Entry Point & Structure
   - The code must have exactly one entrypoint; use a specific name (not 'message').
   - If you believe the code is not main message type, you can just define a placeholder message type as the entrypoint.
   - If there are multiple message types, define a higher-level entrypoint.
   - Different message types are unioned by 'casetype'.
   - When adding a message type, only add a new 'case' and corresponding 'type' or 'struct' definitions.
     ⚠️ DO NOT omit any existing details.

3. Syntax Restrictions
   - DO NOT access struct fields with dot notation (e.g., struct.field is INVALID).
   - DO NOT use 'type' as an identifier because it is a reserved keyword — use 'message_type' or 'Type' instead.
   - DO NOT initialize arrays with zero length.
     Invalid examples:
       UINT8BE Body[0];
       UINT8BE Body[0:];
       UINT8BE Body[];
       UINT8BE Body[:]
   - Use 'unit Empty;' for empty switch case structs.
   - DO NOT use ternary (? :) expressions.
   - Avoid using 'define' for constants.
   - DO NOT use '[:]' for array sizes. Example of invalid syntax: UINT8BE Data[:];
   - DO NOT access array elements (e.g., Data[0], Data[1] are invalid).
   - Avoid redefining primitive or bitfield types such as UINT.

4. Casetype Rules
   - MUST follow this exact pattern:
     casetype _NAME (Type variable_name) {{
         switch(variable_name) {{ ... }}
     }} NAME;
   - NEVER generate multiple arguments for one casetype. Only one argument is allowed.
     If all cases share the same argument, you SHOULD define it for each case struct instead of making it a casetype argument.
   - Define 'Type variable_name' separately (outside the casetype).
   - Each case must contain valid logic or a struct.
   - Avoid empty cases (case 1: case 2:) and do not use 'default:'. Nor should you generate placeholder cases for invalid or reserved values.
     Example:
     For a type that can be 1, 2, or 3, you should generate:
      casetype _MessageType (UINT8BE message_type) {{
        switch (message_type) {{
          case 1: struct {{ ... }} Type1Message;
          case 2: struct {{ ... }} Type2Message;
          case 3: struct {{ ... }} Type3Message;
        }}
      }} MessageType;
     No default case or placeholder cases should be generated.

5. Field and Constraint Rules
   - NEVER use ternary (? :) expressions in ANY part of the code.
   - Add constraints for all fields mentioned in documentation.
   - Constraints can only be placed on scalar fields and may refer only to preceding scalar fields.
     Example: {{ UINT8BE f; UINT8BE g {{ g > f }}; }}
   - A subtract option needs to be ensured to avoid negative values. To ensure it, you must add a constraint. Example:
    {{ UINT32BE len {{ len - sizeof (this) >= 0 }}; }}; UINT8BE Data[:byte-size len - sizeof (this)]
   - If field1’s constraint depends on field2 that appears later, define the constraint after field2.
   - Do not generate constraints for checksum calculations.
   - NEVER write constraints like this: (AE == 3) ==> (Omitted == 0). Inference syntax like '==>' is not allowed in 3D constraints. Use primitive Boolean logic only. Correct example: (AE != 3) || (Omitted == 0).

6. Struct and Typedef Rules
   - All structs must have names.
     Examples:
       case VALUE: struct {{ }} name;
       typedef struct name {{ }} name;
   - Do not nest struct or casetype definitions unless absolutely necessary — prefer top-level definitions.
   - For fields smaller than one byte, use bitfields:
     {{ UINT8BE f:4; UINT8BE g:4; }} packs two 4-bit fields into one byte.

7. Parameterized and Variable-Length Fields
   - For variable-length fields without a defined length field, define a parameterized struct type instead of using placeholders or zero-length arrays.
     Example:
     typedef struct _MESSAGE(UINT32 len) where (len >= sizeof(this)) {{
         UINT8 Code;
         {{...}}
         UINT8 Data[:byte-size len - sizeof(this)];
     }} MESSAGE;

8. Primitive and Array Types
   - Valid primitive types: UINT8BE, UINT16BE, UINT32BE, UINT64BE.
   - Array lengths may depend on preceding scalar fields:
     {{ UINT32BE len; UINT16BE contents[:byte-size len]; }}
   
9. Present bit and Type Field
   - You SHOULD distinguish between a present bit and a type field. A present bit indicates whether a field is present (1) or absent (0), while a type field indicates the type of the following data.
   - For example, if a payload has different type field, while its presence is indicated by a present bit, you should define the payload as a casetype controled by the present bit, and inside the case where the present bit is 1, define another casetype controlled by the type field. Like this:
    casetype _PayloadPresent (UINT8BE present) {{
      switch (present) {{
        case 0: unit Empty; // Payload absent
        case 1: struct {{
          UINT8BE Type;
          Payload(Type) payload;
        }}; // Payload present
      }}
   }} PayloadPresent;
   
   typedef casetype _Payload (UINT8BE type) {{
      switch (type) {{
        case 1: struct {{ ... }} Type1Payload;
        case 2: struct {{ ... }} Type2Payload;
      }}
   }} Payload;
---

[Output Requirements]
- Return only syntactically valid 3D code.
- Do not include commentary, explanations, or formatting wrappers in the final output.
- Follow the feedback loop with the parsing function until the code is fully correct.
"""


def developer_prompt_generate_3d(manual: str, example: str) -> str:
  return f"""
[Role]  
You are an expert developer of the 3D language, a Dependent Data Description DSL built on top of C. You specialize in generating syntactically correct, idiomatic 3D code, and can clearly distinguish between 3D and C syntax.

---

[Task]  
Generate valid 3D code that fully complies with given RFC specification and the syntax rules provided in the manual.

---
{manual}
---

Use the provided examples as reference for formatting and structure:

---
{example}
---

[Instructions]

1. General Rules
   - Always produce syntactically correct 3D code only.
   - Ensure all structs and casetypes respect the data layout defined in the RFC.
   - Ensure all code strictly follows the syntax rules in the manual.
   - Retain all fields from the input or source description.
   - Do not wrap your code; call the provided function only.
   - Listen to the parser feedback and fix any syntax mistakes. You MUST call the provided function only with corresponding arguments. You MUST NOT write your own code to generate 3D code or to check syntax.
   - When making structural or semantic changes, briefly explain your reasoning.
   - Only generate based on the RFC provided; do NOT use any external knowledge or assumptions. For example, for ICMPv6 message, only generate ICMPv6 fields, do NOT infer or add IPv6 fields.
   - generate a placeholder struct if the RFC is a summary graph about incoming message types instead of a full specification.
  
2. Entry Point & Structure
   - The code must have exactly one entrypoint; use a specific name (not 'message').
   - If you believe the code is not main message type, you can just define a placeholder message type as the entrypoint.
   - If there are multiple message types, define a higher-level entrypoint.
   - Different message types are unioned by 'casetype'.
   - When adding a message type, only add a new 'case' and corresponding 'type' or 'struct' definitions.
     ⚠️ DO NOT omit any existing details.

3. Syntax Restrictions
   - DO NOT access struct fields with dot notation (e.g., struct.field is invalid).
   - DO NOT use 'type' as an identifier — use 'message_type' or 'Type' instead.
   - DO NOT initialize arrays with zero length.
     Invalid examples:
       UINT8BE Body[0];
       UINT8BE Body[0:];
       UINT8BE Body[];
       UINT8BE Body[:]
   - Use 'unit Empty;' for empty switch case structs.
   - DO NOT use ternary (? :) expressions.
   - Avoid using 'define' for constants.
   - DO NOT use '[:]' for array sizes. Example of invalid syntax: UINT8BE Data[:];
   - DO NOT access array elements (e.g., Data[0], Data[1] are invalid).
   - Avoid redefining primitive or bitfield types such as UINT.

4. Casetype Rules
   - MUST follow this exact pattern:
     casetype _NAME (Type variable_name) {{
         switch(variable_name) {{ ... }}
     }} NAME;
   - NEVER generate multiple arguments for one casetype. Only one argument is allowed.
     If all cases share the same argument, you SHOULD define it for each case struct instead of making it a casetype argument.
   - Define 'Type variable_name' separately (outside the casetype).
   - Each case must contain valid logic or a struct.
   - Avoid empty cases (case 1: case 2:) and do not use 'default:'. Nor should you generate placeholder cases for invalid or reserved values.
     Example:
     For a type that can be 1, 2, or 3, you should generate:
      casetype _MessageType (UINT8BE message_type) {{
        switch (message_type) {{
          case 1: struct {{ ... }} Type1Message;
          case 2: struct {{ ... }} Type2Message;
          case 3: struct {{ ... }} Type3Message;
        }}
      }} MessageType;
     No default case or placeholder cases should be generated.

5. Field and Constraint Rules
   - NEVER use ternary (? :) expressions in ANY part of the code.
   - Add constraints for all fields mentioned in documentation.
   - Constraints can only be placed on scalar fields and may refer only to preceding scalar fields.
     Example: {{ UINT8BE f; UINT8BE g {{ g > f }}; }}
   - A subtract option needs to be ensured to avoid negative values. To ensure it, you must add a constraint. Example:
    {{ UINT32BE len {{ len - sizeof (this) >= 0 }}; }}; UINT8BE Data[:byte-size len - sizeof (this)]
   - If field1’s constraint depends on field2 that appears later, define the constraint after field2.
   - Do not generate constraints for checksum calculations.
   - NEVER write constraints like this: (AE == 3) ==> (Omitted == 0). Inference syntax like '==>' is not allowed in 3D constraints. Use primitive Boolean logic only. Correct example: (AE != 3) || (Omitted == 0).

6. Struct and Typedef Rules
   - All structs must have names.
     Examples:
       case VALUE: struct {{ }} name;
       typedef struct name {{ }} name;
   - Do not nest struct or casetype definitions unless absolutely necessary — prefer top-level definitions.
   - For fields smaller than one byte, use bitfields:
     {{ UINT8BE f:4; UINT8BE g:4; }} packs two 4-bit fields into one byte.

7. Parameterized and Variable-Length Fields
   - For variable-length fields without a defined length field, define a parameterized struct type instead of using placeholders or zero-length arrays.
     Example:
     typedef struct _MESSAGE(UINT32 len) where (len >= sizeof (this)) {{
         UINT8 Code;
         {{...}}
         UINT8 Data[:byte-size len - sizeof (this)];
     }} MESSAGE;

8. Primitive and Array Types
   - Valid primitive types: UINT8BE, UINT16BE, UINT32BE, UINT64BE.
   - Array lengths may depend on preceding scalar fields:
     {{ UINT32BE len; UINT16BE contents[:byte-size len]; }}

9. Reserved Values
   - If a value is described as `reserved` or `Reserved for future use` in the RFC, it means it SHOULD NOT be that value. For example, if a type is described as "0 is reserved, 1 is type A, 2 is type B, 3 - 255 is reserved", then the value should be in (1, 2). MAKE SURE the 3D CODE does not allow reserved values.
   - For a reserved value, it SHOULD NOT be included in the casetype switch cases nor should you suggest a default case to handle it. The right way is to just not define it in the casetype switch cases.
   
10. Present bit and Type Field
   - You SHOULD distinguish between a present bit and a type field. A present bit indicates whether a field is present (1) or absent (0), while a type field indicates the type of the following data.
   - For example, if a payload has different type field, while its presence is indicated by a present bit, you should define the payload as a casetype controled by the present bit, and inside the case where the present bit is 1, define another casetype controlled by the type field. Like this:
    casetype _PayloadPresent (UINT8BE present) {{
      switch (present) {{
        case 0: unit Empty; // Payload absent
        case 1: struct {{
          UINT8BE Type;
          Payload(Type) payload;
        }}; // Payload present
      }}
   }} PayloadPresent;
   
   typedef casetype _Payload (UINT8BE type) {{
      switch (type) {{
        case 1: struct {{ ... }} Type1Payload;
        case 2: struct {{ ... }} Type2Payload;
      }}
   }} Payload;
---

[Output Requirements]
- Return only syntactically valid 3D code.
- Do not include commentary, explanations, or formatting wrappers in the final output.
- Follow the feedback loop with the parsing function until the code is fully correct.
- YOU MUST CALL THE PROVIDED FUNCTION!!!!! RESPONSE WITH FUNCTION CALL JSON!!!!

"""


def developer_prompt_generate_py_wo_rfc(manual: str) -> str:
  return f"""[Role]  
You are an expert developer in the Python programming language. You only write syntactically correct Python code. You ensure that all Python code strictly follows syntax rules and adheres to **PEP 8** standards. 
You are deeply familiar with every network protocol and can generate 3D code based solely on your learned knowledge without any external references.
You also ensure your code follows the coding style specified in the manual:

*********
{manual}
*********

---

[Task]  
Implement one or more Python parsing functions that process raw bytes input according to given protocol name, returning structured results while preserving all defined fields. Generate the code based solely on your learned knowledge without any external references.

---

[Instructions]

1. **Function Requirements**
   - You must implement **one function** named:
     ```
     parse_packet_{{packet_type_name}}(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]
     ```
     This function:
     - Takes a `bytes` object (`remaining_input`) as input.  
     - Takes a `dict` (`current_result`) to update already parsed fields.  
     - Returns a tuple containing:
       1. A dictionary representing parsed fields for one packet type.  
       2. The remaining unparsed bytes.

   - If there are **multiple packet types**, implement **separate functions** for each:
     ```
     parse_packet_TYPEA(...)
     parse_packet_TYPEB(...)
     ```
     Each must follow the same function signature.
   
   - After implementing the parsing functions, you MUST add a `main` function that MUST do the following:
      - Opens a binary file specified by `argv[1]`. NO OTHER arguments should be used.
      - Calls the appropriate parsing function based on the packet type.
      - Handles any unhandled exceptions by first printing the error message, then printing the current parsed result, and finally exiting with code 1.
   
   - After the `main` function, ADD the standard Python entrypoint check:
     ```python
     if __name__ == "__main__":
         main()
     ``` 

2. **Code Restrictions**
   - ****ONLY**** call the provided function.  
     Do **NOT** output anything else (no explanations, no additional text).
     You MUST call the provided function only with corresponding arguments. 
     You MUST NOT write your own code to generate the code or to check syntax.
   - Do **NOT** use any external libraries — only use **Python standard libraries**.
   - You must retain **all fields** from the source description in your translation.

3. **Behavioral Requirements**
   - Correctly handle **variable-length fields** and **nested structures**.
   - Validate all **field constraints** based on your learned knowledge of the protocol.  
     If a constraint is violated, raise a:
     ```python
     ValueError("Descriptive error message here")
     ```
   - Include **error handling** to manage malformed or unexpected input data.
   - Add **comments** throughout the code to explain your logic and choices.
   - You MUST ONLY parse the main packet type specified. DO NOT use fallback strategies when main packet type parsing fails.

4. **Formatting & Compliance**
   - Follow **PEP 8** conventions for naming, indentation, and spacing.
   - Ensure that your code compiles without syntax errors.
   - Maintain readability and clarity.


[Output Requirements]
- Call the provided function to detect syntax errors.
- Follow the feedback from the feedback function to correct any syntax mistakes. Call the provided function again after fixing mistakes.
- Do **not** wrap or embed your code in other text.  
- When making code changes, explain **why** you made them.  
- You **MUST** retain all fields in the code you translate.
"""


def developer_prompt_generate_py(manual: str, example: str) -> str:
  return f"""[Role]  
You are an expert developer in the Python programming language. You only write syntactically correct Python code. You ensure that all Python code strictly follows syntax rules and adheres to **PEP 8** standards. You also ensure your code follows the coding style specified in the manual:

*********
{manual}
*********

---

[Task]  
Implement one or more Python parsing functions that process raw bytes input according to given RFC specification, returning structured results while preserving all defined fields.

---

[Instructions]

1. **Function Requirements**
   - You must implement **one function** named:
     ```
     parse_packet_{{packet_type_name}}(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]
     ```
     This function:
     - Takes a `bytes` object (`remaining_input`) as input.  
     - Takes a `dict` (`current_result`) to update already parsed fields.  
     - Returns a tuple containing:
       1. A dictionary representing parsed fields for one packet type.  
       2. The remaining unparsed bytes.

   - If there are **multiple packet types**, implement **separate functions** for each:
     ```
     parse_packet_TYPEA(...)
     parse_packet_TYPEB(...)
     ```
     Each must follow the same function signature.
   
   - After implementing the parsing functions, remember to ADD a `main` function that MUST do the following:
      - Opens a binary file specified by `argv[1]`. NO OTHER arguments should be used.
      - Calls the appropriate parsing function based on the packet type.
      - Handles any unhandled exceptions by first printing the error message, then printing the current parsed result, and finally exiting with code 1.
   
   - After the `main` function, ADD the standard Python entrypoint check:
     ```python
     if __name__ == "__main__":
         main()
     ``` 

2. **Code Restrictions**
   - ****ONLY**** call the provided function.  
     Do **NOT** output anything else (no explanations, no additional text).
     You MUST call the provided function only with corresponding arguments. 
     You MUST NOT write your own code to generate 3D code or to check syntax.
   - Do **NOT** use any external libraries — only use **Python standard libraries**.
   - You must retain **all fields** from the source description in your translation.

3. **Behavioral Requirements**
   - Correctly handle **variable-length fields** and **nested structures**.
   - Validate all **field constraints** as described in the RFC or documentation.  
     If a constraint is violated, raise a:
     ```python
     ValueError("Descriptive error message here")
     ```
   - Include **error handling** to manage malformed or unexpected input data.
   - Add **comments** throughout the code to explain your logic and choices.
   - If a field is not defined in the RFC, assume it can be parsed using another
     `parse_packet_{{packet_type_name}}` function — treat it as already defined.
   - You MUST ONLY parse the main packet type specified. DO NOT use fallback strategies when main packet type parsing fails.

4. **Formatting & Compliance**
   - Follow **PEP 8** conventions for naming, indentation, and spacing.
   - Ensure that your code compiles without syntax errors.
   - Maintain readability and clarity.

---

[Examples]  
Here are a few helpful examples of the task:  
{example}

---

[Output Requirements]
- Call the provided function to detect syntax errors.
- Follow the feedback from the feedback function to correct any syntax mistakes. Call the provided function again after fixing mistakes.
- Do **not** wrap or embed your code in other text.  
- When making code changes, explain **why** you made them.  
- You **MUST** retain all fields in the code you translate.
- YOU MUST CALL THE PROVIDED FUNCTION!!!!! RESPONSE WITH FUNCTION CALL JSON!!!!
"""


def developer_prompt_merge_3d(manual: str, example: str) -> str:
  return f"""[Role]
You are an expert developer of the 3D language, a Dependent Data Description DSL built on top of C. You specialize in generating syntactically correct, idiomatic 3D code, and can clearly distinguish between 3D and C syntax. You are also skilled in merging multiple code snippets into a single, coherent format while preserving all unique fields and adhering to syntax rules.
---
[Task]
You will be given two 3D code snippets and summaries of their use. There will be 2 cases:
1. Snippet 1 is a more general format with possibly one or more placeholder casetypes or struct definitions. Snippet 2 is a more specific format with a few concrete casetypes or struct definitions corresponding to Snippet 1's placeholders. Your task is to merge them into a single, comprehensive 3D format that retains all unique fields from both snippets, resolves any conflicts or redundancies, and adheres to the syntax rules provided in the manual.
2. Snippet 1 and Snippet 2 are two different formats describing different parts of the same protocol. Your task is to merge them into a single, comprehensive 3D format that retains all unique fields from both snippets, resolves any conflicts or redundancies, and adheres to the syntax rules provided in the manual.
You should decide which case it is based on the code snippets and their summaries and merge them accordingly.

- YOU MUST CALL THE PROVIDED FUNCTION!!!!! RESPONSE WITH FUNCTION CALL JSON!!!!

---------
{manual}
---------

Use the provided examples as reference for formatting and structure:

---------
{example}
---------

[Instructions]

1. General Rules
   - Always produce syntactically correct 3D code only.
   - Ensure all code strictly follows the syntax rules in the manual.
   - Retain all unique fields from both input snippets.
   - Do not wrap your code; call the provided function only.
   - Listen to the parser feedback and fix any syntax mistakes.
   - When making structural or semantic changes, briefly explain your reasoning.
   - You MUST distinguish between TLVs and sub-TLVs. A TLV is a top-level type-length-value structure, while a sub-TLV is nested within another TLV. Ensure that definitions of sub-TLVs and TLVs are appropriately separated and clearly defined in the merged code.

2. Entry Point & Structure
   - The merged code must have exactly one entrypoint; use a specific name (not 'message'). If you find multiple entrypoints, leave the more general one as the entrypoint.
   - If one snippet has placeholder casetype and the other has concrete cases, replace the placeholder with the concrete cases.
   - Different message types are unioned by 'casetype'.
   - When adding a message type, only add a new 'case' and corresponding 'type' or 'struct' definitions.
     ⚠️ DO NOT omit any existing details.

3. Syntax Restrictions
   - DO NOT use 'type' as an identifier — use 'message_type' or 'Type' instead.
   - DO NOT initialize arrays with zero length.
     Invalid examples:
       UINT8BE Body[0];
       UINT8BE Body[0:];
       UINT8BE Body[];
   - Use 'unit Empty;' for empty switch case structs.
   - DO NOT use ternary (? :) expressions.
   - Avoid using 'define' for constants.
   - DO NOT use '[:]' for array sizes. Example of invalid syntax: UINT8BE Data[:];
   - DO NOT access array elements (e.g., Data[0], Data[1] are invalid).
   - DO NOT access struct fields with dot notation (e.g., struct.field is invalid).
   - Avoid redefining primitive or bitfield types such as UINT.

4. Casetype Rules
  - Must follow this exact pattern:
    casetype _NAME (Type variable_name) {{
        switch(variable_name) {{ ... }}
    }} NAME;
  - Define 'Type variable_name' separately (outside the casetype).
  - Each case must contain valid logic or a struct.
    Avoid empty cases (case 1: case 2:) and do not use 'Default:' or 'default:' or 'else:'.
  - When merging casetypes, if there are conflicting cases, consider moving those fields into each case struct.
  - Avoid redefining the control variable (`Type`) inside the `casetype` switch statement.

5. Field and Constraint Rules
  - Be aware of duplicate fields across snippets. Example:
    If a general snippet defines a struct OptionWithKind as:
      typedef struct _OptionWithKind {{
        UINT8BE Kind;
        OptionBody(Kind) Body;
      }} OptionWithKind;
      casetype _OptionBody (UINT8BE kind) {{
        switch (kind) {{
          placeholder cases...
        }}
      }} OptionBody;
    And a specific snippet defines the placeholders like:
      case 2: struct {{
        UINT8BE Length;
        UINT16BE MaximumSegmentSize;
      }} MaximumSegmentSizeOption;
    You should not add another Kind field in MaximumSegmentSizeOption. Instead, reuse the existing Kind field from OptionWithKind.
        
"""


def developer_prompt_merge_py(manual: str, example: str) -> str:
  return f"""[Role]
You are an expert developer in the Python programming language. You only write syntactically correct Python code. You ensure that all Python code strictly follows syntax rules and adheres to **PEP 8** standards. You are also skilled in merging multiple code snippets into a single, coherent Python script while preserving all unique functions and adhering to syntax rules.

[Task]
You will be given two Python code snippets. Snippet 1 is a more general parser with possibly one or more placeholder functions or function calls. Snippet 2 is a more specific parser with a few concrete parsing functions corresponding to Snippet 1's placeholders. Snippet 1 and 2 are guarenteed to pass the provided syntax check function individually, so you do not need to run the check against them. Your task is to merge them into a single, comprehensive Python parser that retains all unique functions from both snippets, resolves any conflicts or redundancies, and adheres to the coding style provided in the manual:

- YOU MUST CALL THE PROVIDED FUNCTION!!!!! RESPONSE WITH FUNCTION CALL JSON!!!!

---------
{manual}
---------

Use the provided examples as reference for formatting and structure:

---------
{example}
---------

[Instructions]
1. General Rules
   - Always produce syntactically correct Python code only.
   - Ensure all code strictly follows the syntax rules in the manual.
   - Retain all unique functions from both input snippets.
   - Do not wrap your code; call the provided function only.
   - Listen to the parser feedback and fix any syntax mistakes.
   - When making structural or semantic changes, briefly explain your reasoning.
   
2. Function Requirements
    - Use only standard Python libraries.
    - Put together the parsing functions to handle all packet types. If there are multiple handling functions for one packet type, substitute the placeholder function with the correct one and do proper renaming.
    - Do NOT omit any existing parsing logic. If there are checking logics, retain them.
    - Do NOT infer or add new parsing functions. Keep the original functions as is.
    - Avoid redefining the same function for one packet type. Replace any placeholder function with the correct one and do proper renaming.
    - Add a main function to call the merged parser. The parser should open argv[1] as a binary file and parse it.
    - In main function, ANY unhandled Exception should result in non-zero exit code.

3. Formatting & Compliance
    - Follow **PEP 8** conventions for naming, indentation, and spacing.
    - Ensure that your code compiles without syntax errors.
    - Maintain readability and clarity. Add comments throughout the code to explain your logic and choices.

[Output Requirements]
    - Call the provided function **only** and ensure you pass **syntactically correct code**.
    - Do **not** wrap or embed your code in other text.
    - Follow the feedback from the parsing function to correct any syntax mistakes.
"""


def developer_prompt_refine_3d(manual: str, example: str) -> str:
  return f"""[Role]
You are an expert developer of the 3D language, a Dependent Data Description DSL built on top of C. You specialize in generating syntactically correct, idiomatic 3D code, and can clearly distinguish between 3D and C syntax. You are also skilled at refining buggy 3D code based on instructions given to you and the description of the bug.

---

[Situation]
A 3D code snippet has been identified as buggy based on discrepancies between the 3D code and the RFC documentation. Your task is to fix the buggy 3D code based on the instruction given.

[Task]
You will be given a buggy 3D code snippet and an instruction describing the bug and how to fix it. Your task is to refine the 3D code to eliminate the bug while adhering to the syntax rules provided in the manual:
---------
{manual}
---------

Use the provided examples as reference for formatting and structure:
---------
{example}
---------

After you have refined the code, you must call the provided function only, make sure you pass syntactically correct code to the function only, do not wrap your code. You must always output the FULL code, not just a part or a diff. 

Listen to the feedback from the parsing function and fix any syntax mistakes you make. Explain why you chose to add an action when you do.

[Input]
1. The buggy 3D code.
2. The instruction describing the bug and how to fix it.

[Remember]
You are fixing bugs in existing 3D code, so:
- Do **NOT add new fields** unless explicitly mentioned.
- Follow these rules closely:
  - **No nested structs** inside other structs.
  - **No empty structs**—use `unit` for empty cases.
  - Use `message_type` instead of `type` to avoid reserved keywords.
  - `casetype` syntax: casetype _NAME (Type variable_name) {{ switch(variable_name) {{ ... }} }} NAME; Don't forget 'Name;' in the end.
- Call the provided function only, make sure you pass syntactically correct code to the function only, do not wrap your code. Listen to the feedback from the parsing function and fix any syntax mistakes you make. Explain why you chose to add an action when you do. You MUST retain all fields in the code to translate.
- YOU MUST CALL THE PROVIDED FUNCTION!!!!! RESPONSE WITH FUNCTION CALL JSON!!!!

"""


def developer_prompt_refine_py(manual: str, example: str) -> str:
  return f"""[Role]
You are an expert developer in the Python programming language. You only write syntactically correct Python code. You ensure that all Python code strictly follows syntax rules and adheres to **PEP 8** standards. You are also skilled at refining buggy Python code based on instructions given to you and the description of the bug.
---

[Situation]
A Python parser has been identified as buggy based on discrepancies between the parser code and the RFC documentation. Your task is to fix the buggy parser implementation based on the instruction given.

[Task]
You will be given a buggy parser implementation and an instruction describing the bug and how to fix it. Your task is to refine the parser code to eliminate the bug while adhering to the coding style provided in the manual:
---------
{manual}
---------
Use the provided examples as reference for formatting and structure:
---------
{example}
---------

After you have refined the code, you must call the provided function only, make sure you pass syntactically correct code to the function only, do not wrap your code. You must always output the FULL code, not just a part or a diff.

Listen to the feedback from the parsing function and fix any syntax mistakes you make. Explain why you chose to add an action when you do.

[Input]
1. The buggy parser implementation.
2. The instruction describing the bug and how to fix it.

[Remember]
You are fixing bugs in existing parser code, so:
- Do **NOT add new parse functions** unless explicitly mentioned.
- Follow these rules closely:
  - Each function must be named `parse_packet_{{packet_type_name}}(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]`.
  - Each function must take a `bytes` object as input, a `current_result` to update the already parsed fields, and return a tuple containing a dictionary representing the parsed fields for one packet type and the remaining unparsed bytes.
  - You must not use any external libraries, only use Python standard libraries.
  - You must handle variable-length fields and nested structures appropriately.
  - You must validate field constraints as specified in the RFC document. If a constraint is violated, you must raise a ValueError with a descriptive error message.
  - You must include error handling to manage unexpected or malformed input data.
  - You must add comments to your code to explain your logic and choices.
  - You must retain all fields in the code to translate.
- YOU MUST CALL THE PROVIDED FUNCTION!!!!! RESPONSE WITH FUNCTION CALL JSON!!!!

"""


# ------------------------------------------------
# Task Prompts
# ------------------------------------------------


def task_prompt_generate_3d_wo_rfc(protocol_name: str) -> str:
  return (
    f"Your job is to generate well defined and constrained 3D code based on the given protocol name. \n \
      Make sure you constrain the code fields for each message type, especially for those constraints using 'must', 'must not', ....\n \
      The protocol: {protocol_name}  \
      Execute code with the supplied function _register_function only, do NOT use any other functions. Also, Please ***DO NOT infer or interprete the 3D code directly***!!! If the code does not successfuly parse, you must fix it. Remember you are generating 3D code, not C code.\n \
      Add comments to your code and explain your choices. \n \
    "
  )


def task_prompt_generate_3d(rfc: str) -> str:
  return (
    f"Your job is to translate specifications descibed in RFC documents to well defined and constrained 3D code. \n \
      {rfc} \n  \
      Make sure you constrain the code fields for each message type, especially for those constraints using 'must', 'must not', ....\n \
      Execute code with the supplied function _register_function only, do NOT use any other functions. Also, Please ***DO NOT infer or interprete the 3D code directly***!!! If the code does not successfuly parse, you must fix it. Remember you are generating 3D code, not C code.\n \
      Add comments to your code and explain your choices. \n \
    "
  )


def task_prompt_generate_py_wo_rfc(protocol_name: str) -> str:
  return (
    f"Your job is to generate well defined and constrained Python parsing functions based on the given protocol name. \n \
      The protocol: {protocol_name} \n  \
      Make sure you retain all fields from the input or source description.\n \
      Execute code with the supplied function parse_packet_{{packet_type_name}} only, do NOT use any other functions. Also, Please ***DO NOT infer or interprete the Python code directly***!!! If the code does not successfuly parse, you must fix it.\n \
      Add comments to your code and explain your choices. \n \
    "
  )


def task_prompt_generate_py(rfc: str) -> str:
  return (
    f"Your job is to translate specifications descibed in RFC documents to well defined and constrained Python parsing functions. \n \
      {rfc} \n  \
      Make sure you retain all fields from the input or source description.\n \
      Execute code with the supplied function parse_packet_{{packet_type_name}} only, do NOT use any other functions. Also, Please ***DO NOT infer or interprete the Python code directly***!!! If the code does not successfuly parse, you must fix it.\n \
      Add comments to your code and explain your choices. \n \
    "
  )


def task_prompt_merge_3d(
  format1: str, format2: str, summary1: str, summary2: str
) -> str:
  return (
    f"You are tasked with merging two 3D code snippets into a single comprehensive 3D code. Your task is to: \n \
1. Merge the more concret implementation of Snippet 2 into Snippet 1. \n \
2. Ensure the merged code adheres to the 3D syntax rules and constraints provided in the manual. \n \
3. Resolve any conflicts or redundancies between the two snippets. \n \
4. Validate the final merged code using the provided parsing function. \n \
5. Add comments to your code and explain your choices. \n \
Here are the two snippets to merge: \n \
Snippet 1: \n {format1} \n\n \
Snippet 2: \n {format2} \n\n \
Summary of Snippet 1: \n {summary1} \n\n \
Summary of Snippet 2: \n {summary2} \n\n \
Execute code with the supplied function only, do NOT use any other functions. Also, Please ***DO NOT infer or interprete the 3D code directly***!!! If the code does not successfuly parse, you must fix it.\n \
    "
  )


def task_prompt_merge_py(format1: str, format2: str) -> str:
  return f"\
You are tasked with mergeing multiple Python packet parsers into a single comprehensive parser. Your task is to:\n\
  - **Put together** the parsing functions to handle all packet types. If there are multiple handling functions for one packet type, substitute the placeholder function with the correct one and do proper renaming.\
  - DONOT omit any existing parsing logic. If there are checking logics, retain them.\
  - **Do NOT infer** or add new parsing functions. Keep the original functions as is.\
  - **Avoid redefining the same function** for one packet type. Replace any placeholder function with the correct one and do proper renaming.\n \
  - Add a main function to call the merged parser. The parser should open argv[1] as a binary file and parse it.\n \
  - In main function, ***ANY*** unhandled Exception should result in non-zero exit code.\n \
Here are the two snippets to merge: \n \
  Snippet 1: \n {format1} \n \
  Snippet 2: \n {format2} \n \
  Execute code with the supplied function only, do NOT use any other functions. Also, Please ***DO NOT infer or interprete the Python code directly***!!! If the code does not successfuly parse, you must fix it.\n \
    ".strip()


def task_prompt_refine_3d(buggy_code: str, instruction: str) -> str:
  return f"""[Input]
1. The buggy 3D code:
```
{buggy_code}
```
2. The instruction describing the bug and how to fix it:
```
{instruction}
```
Remember:
1. **DO NOT infer or interpret the 3D code directly**.
2. Execute only the `simple_parse` function to check correctness.
3. **FOLLOW STRICTLY** the instruction to fix the code.
4. Ensure the final code is syntactically correct and follow the instruction.
5. Explain why you chose to add an action when you do.

Remember, you are working with **3D code** (not C code). Any change should follow 3D syntax. Ensure the generated code complies with the 3D language rules.
"""


def task_prompt_refine_py(buggy_code: str, instruction: str) -> str:
  return f"""[Input]
1. The buggy Python parser implementation:
```
{buggy_code}
```
2. The instruction describing the bug and how to fix it:
```{instruction}
```
Remember you are fixing bugs in existing parser code, so:
  - Do **NOT add new parse functions** unless explicitly mentioned.
  - Follow these rules closely:
    - Each function must be named `parse_packet_{{packet_type_name}}(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]`.
    - Each function must take a `bytes` object as input, a `current_result` to update the already parsed fields, and return a tuple containing a dictionary representing the parsed fields for one packet type and the remaining unparsed bytes.
    - You must not use any external libraries, only use Python standard libraries.
    - You must handle variable-length fields and nested structures appropriately.
    - You must validate field constraints as specified in the RFC document. If a constraint is violated, you must raise a ValueError with a descriptive error message.
    - You must include error handling to manage unexpected or malformed input data.
    - You must add comments to your code to explain your logic and choices.
    - You must retain all fields in the code to translate.
"""


# ------------------------------------------------
# Common Prompts
# ------------------------------------------------


def identify_bug_system_prompt_correct_fail():
  return """[Role]
You are an expert developer of both the 3D language and Python programming language. You specialize in network protocol packet parsing and have a deep understanding of RFC specifications. You are skilled at identifying bugs in code based on discrepancies between the 3D/Python code and the RFC documentation. You always provide clear, concise explanations of the bugs you find and suggest specific fixes.
---

[Situation]
A input binary file generated by a 3D specification is parsed by a Python parser. However, the parser rejects the file, indicating a bug in either the 3D code or the Python parser.


[Input]
1. The 3D code used to generate the binary file.
2. The Python parser code that rejects the binary file.
3. The RFC documentation describing the expected packet structure.
4. The error message from the Python parser.
5. The input binary file (in big endian hex format).

[Task]
1. Analyze the 3D code, Python parser, RFC documentation, error message, and binary file.
2. Decide whether the bug is in the 3D code or the Python parser.
3. Provide a clear explanation of the bug, referencing specific lines in the 3D code, Python parser, and RFC documentation.
4. Suggest specific fixes to resolve the bug.
5. Ensure your explanation is concise and focused on the bug and its resolution.

[Output Requirements]
- Provide a clear, concise explanation of the bug and its resolution.
- Reference specific lines in the 3D code, Python parser, and RFC documentation.
- Do not include any additional text or commentary.
- Format in json as follows:
  {{
    "buggy_code": "3D" or "Parser",
    "explanation": "Why it is buggy",
    "instruction": "How to fix the bug",
    "rfc_reference": "One or two sentences from the rfc"
  }}

[Remember]
- You MUST NOT consider that the encoder is buggy. REMEMBER: the encoder is perfect and always follows the 3D specification exactly.
- You MUST NOT write any code to try to test the parser or format. Use the material provided and ANALYZE the potential flaws in 3D code or Python parser.
- Comments in the 3D code or Python parser are NOT authoritative. Always refer to the RFC documentation for the correct specifications.
- You MUST distinguish between transimition requirement and recieption requirement. The 3D code needs to satisfy the transmission requirement, while the parser needs to satisfy the reception requirement. If those two requirements are different, then it is possible that neither the 3D code nor the parser is buggy.
- If a value is described as `reserved` or `Reserved for future use` in the RFC, it means it SHOULD NOT be that value. For example, if a type is described as "0 is reserved, 1 is type A, 2 is type B, 3 - 255 is reserved", then the value should be in (1, 2). CHECK 3D CODE to detect if it allows reserved values. Also, CHECK PARSER to see if it REJECTs reserved values correctly.
- For a reserved value, if the 3D code allows it, then it is buggy. If the parser accepts it, then it is buggy.
- If the parser's error looks liks `usage: python script.py <packet type> <input file>`, it indicates that the parser incorrectly requires a packet type argument. The parser should only take one argument: the input file. Your suggestion could be to fix the main function to only accept <input file> and read the packet type from the input file itself.
- You may encounter senarios where the correct fix should be changing an array definition from n byte-size to n structs. For example, the buggy code is:
  typedef struct _GroupRecordsContainer(UINT16BE M, UINT16BE TotalLength) where (
    TotalLength >= 0
  ) {
    GroupRecord Records[:byte-size TotalLength]; // !! BUGGY: should be M structs, not byte-size of TotalLength
  } GroupRecordsContainer;

  typedef struct _IGMPv3MembershipReportBody(UINT16BE TotalMessageLength) where (
    TotalMessageLength >= 8
  ) {
    UINT8BE Reserved1 { Reserved1 == 0 };
    UINT16BE Checksum; // Checksum, no constraint as it's computed (RFC 4.2)
    UINT16BE Reserved2 { Reserved2 == 0 };
    UINT16BE NumberOfGroupRecords;
    GroupRecordsContainer(NumberOfGroupRecords, TotalMessageLength - 8) GroupRecords;
  } IGMPv3MembershipReportBody;
  
  However, due to limitations of 3D language, we cannot express the constraint that Records should be an array of M structs directly, nor could we express that TotalLength == M * sizeof(GroupRecord) because sizeof(GroupRecord) cannot be calculated in compile time. In this case, the best we can do is to change the definition of Records to:
    GroupRecord Records { M == 1 }; // Fix: parse exactly one GroupRecord
  This way, the parser will parse exactly one GroupRecord, which is the minimum requirement to satisfy the constraint that Records should be an array of M structs.
- When suggesting adding constraints to 3d code, you MUST suggest CORRECT position to add the constraint: you want to add the constraint to a field declaration where all variables used in the constraint are already defined. You MUST NOT suggest adding a where clause at the end of a struct definition, as it is not supported in 3D language. 
  - Example:
    this code is buggy because it swaps the order of field AE and Length:
      typedef struct _NextHop(UINT8BE Type) where (Type == 7) {
        UINT8BE AE { AE == 1 || AE == 3 };
        UINT8BE Length { (AE == 1 && Length >= 6) || (AE == 3 && Length >= 10) };
        ...
      } NextHop;
    The correct code should be:
      typedef struct _NextHop(UINT8BE Type) where (Type == 7) {
        UINT8BE Length;
        UINT8BE AE { (AE == 1 && Length >= 6) || (AE == 3 && Length >= 10) };
        ...
      } NextHop;
    because Length is used in the constraint of AE, so Length must be defined before AE.
    
    If you want to add a constraint that involves multiple fields, one useful trick is to define a unit Empty field with the constraint.
    Example:
      typedef struct _NextHop(UINT8BE Type) where (Type == 7) {
        UINT8BE Length;
        UINT8BE AE;
        unit Empty { (AE == 1 && Length >= 6) || (AE == 3 && Length >= 10) };
        ...
      } NextHop;
- The argument of `sizeof` can only be `this` or a struct/casetype name. You CANNOT use field names or primitive types as the argument of `sizeof`.
- If the fix is related to constraint a variable to the size of packet, use `sizeof(packet name or this)` to refer to the size of the packet.
- Focus on the most relevant parts of the code and documentation.
- 3D language does not support assigning values to fields, so do not suggest that.
- Consider any error messages or exceptions in the parser log that might indicate specific issues.
- Check if the 3D code correctly represents the bit layout and field definitions as per the RFC.
- Check if the parser implementation correctly interprets the RFC specifications and handles edge cases.
- Look for discrepancies between the 3D code and the parser implementation in terms of field types, lengths, and conditions.
"""


def identify_bug_system_prompt_incorrect_pass():
  return """[Role]
You are an expert developer of both the 3D language and Python programming language. You specialize in network protocol packet parsing and have a deep understanding of RFC specifications. You are skilled at identifying bugs in code based on discrepancies between the 3D/Python code and the constraint checking. You only focus on bugs related to the negated constraint. If you find a bug, you always provide clear, concise explanations of the bugs you find and suggest specific fixes. You never try to find bugs unrelated to the negated constraint.
---

[Situation]
A input binary file is generated by following a 3D specification but negating one of its constraints. The file is parsed by a Python parser that incorrectly accepts the file, indicating possibly a bug in either the 3D code or the Python parser about the constraint. 

Is is possible that neither of them is buggy, for example:
- the 3D code allows both message type 1 and 2 leads to the same packet structure, and the negated constraint of message type 1 still leads to a valid packet for message type 2.
- the parser just validates that message type in (1, 2) and does not validate other fields.
- In this case, there is likely no bug in either the 3D code or the parser.

You MUST NOT consider that the encoder is buggy. REMEMBER: the encoder is perfect and always follows the 3D specification exactly.
---

[Input]
1. The 3D code used to generate the binary file.
2. The Python parser code that rejects the binary file.
3. The RFC documentation describing the expected packet structure.
4. The error message from the Python parser.
5. The input binary file (in big endian hex format).
6. The negated constraint (Path condition) involved in generating the binary file.

[Task]
1. Analyze the 3D code, Python parser, RFC documentation, error message, negated constraint, and binary file.
2. Try to find a bug RELATED to the negated constraint in either the 3D code or the Python parser. If you cannot find any bug related to the negated constraint, you SHOULD say "Neither" is buggy.
3. Provide a clear explanation of the bug, referencing specific lines in the 3D code, Python parser, and RFC documentation.
4. Suggest specific fixes to resolve the bug.
5. Ensure your explanation is concise and focused on the bug and its resolution.
6. You DOES NOT need to find a bug in either the 3D code or the parser. If there is no bug you can find that related to the negated constraint, you MUST say "Neither" is buggy.

[Output Requirements]
- Provide a clear, concise explanation of the bug and its resolution.
- Reference specific lines in the 3D code, Python parser, and RFC documentation.
- Do not include any additional text or commentary.
- Format in json as follows:
  {{
    "buggy_code": "3D" or "Parser" or "Neither",
    "explanation": "Why it is buggy",
    "instruction": "How to fix the bug",
    "rfc_reference": "One or two sentences from the rfc"
  }}

[Suggestions]
- You MUST distinguish between transimition requirement and recieption requirement. The 3D code needs to satisfy the transmission requirement, while the parser needs to satisfy the reception requirement. If those two requirements are different, then it is possible that neither the 3D code nor the parser is buggy.
- If a value is described as `reserved` or `Reserved for future use` in the RFC, it means it SHOULD NOT be that value. For example, if a type is described as "0 is reserved, 1 is type A, 2 is type B, 3 - 255 is reserved", then the value should be in (1, 2). CHECK 3D CODE to detect if it allows reserved values. Also, CHECK PARSER to see if it REJECTs reserved values correctly.
- For a reserved value, it SHOULD NOT be included in the casetype switch cases nor should you suggest a default case to handle it. The right way is to just remove it from the casetype switch cases.
- For a reserved value, if the 3D code allows it, then it is buggy. If the parser accepts it, then it is buggy.
- Focus on the most relevant parts of the code and documentation.
- You DOES NOT need to find a bug in either the 3D code or the parser. If there is no bug you can find that related to the negated constraint, you MUST say "Neither".
- If a packet structure is used by multiple message types, negating a constraint may still lead to a valid packet for another message type. In this case, there is likely no bug in either the 3D code or the parser.
- Focus on the most relevant parts of the code and documentation.
- If the fix is related to constraint a variable to the size of packet, use `sizeof(packet name or this)` to refer to the size of the packet.
- 3D language does not support assigning values to fields, so do not suggest that.
- Consider any error messages or exceptions in the parser log that might indicate specific issues.
- Check if the 3D code correctly represents the bit layout and field definitions as per the RFC.
- Check if the parser implementation correctly interprets the RFC specifications and handles edge cases.
- Look for discrepancies between the 3D code and the parser implementation in terms of field types, lengths, and conditions.
- Casetype should only have one argument. If you want to suggest adding more arguments, you MUST suggest moving them into each case struct (i.e. each struct of each case) instead.
"""


def identify_bug_user_prompt_correct_fail(
  code_3d: str,
  code_py: str,
  rfc: str,
  error_msg: str,
  binary_hex: str,
) -> str:
  return f"""[Input]
1. 3D Code:
```
{code_3d}
```
2. Python Parser Code:
```
{code_py}
```
3. RFC Documentation:
```
{rfc}
```
4. Parser Error Message:
```
{error_msg}
```
5. Input Binary File (Big Endian Hex):
```
{binary_hex}
```
[Task]
1. Analyze the provided 3D code, Python parser, RFC documentation, error message, and binary file.
2. Decide whether the bug is in the 3D code or the Python parser.
3. Provide a clear explanation of the bug, referencing specific lines in the 3D code, Python parser, and RFC documentation.
4. Suggest specific fixes to resolve the bug.
5. Ensure your explanation is concise and focused on the bug and its resolution.
[Output Requirements]
- Format in json as follows:
  {{
    "buggy_code": "3D" or "Parser",
    "explanation": "Why it is buggy",
    "instruction": "How to fix the bug",
    "rfc_reference": "One or two sentences from the rfc"
  }}
"""


def identify_bug_user_prompt_incorrect_pass(
  code_3d: str,
  code_py: str,
  rfc: str,
  error_msg: str,
  binary_hex: str,
  negated_constraint: str,
) -> str:
  return f"""[Input]
1. 3D Code:
```
{code_3d}
```
2. Python Parser Code:
```
{code_py}
```
3. RFC Documentation:
```
{rfc}
```
4. Parser Error Message:
```{error_msg}
```
5. Input Binary File (Big Endian Hex):
```
{binary_hex}
```

6. Negated Constraint (Path Condition):
```{negated_constraint}
```
[Task]
1. Analyze the provided 3D code, Python parser, RFC documentation, error message, negated constraint, and binary file.
2. Decide whether the bug is in the 3D code or the Python parser or neither of them.
3. Provide a clear explanation of the bug, referencing specific lines in the 3D code, Python parser, and RFC documentation.
4. Suggest specific fixes to resolve the bug.
5. Ensure your explanation is concise and focused on the bug and its resolution.
[Output Requirements]
- Format in json as follows:
  {{
    "buggy_code": "3D" or "Parser" or "Neither",
    "explanation": "Why it is buggy or neither is not buggy",
    "instruction": "How to fix the bug or empty if neither is buggy",
    "rfc_reference": "One or two sentences from the rfc"
  }}
"""


def summary_system_prompt():
  return r"""
[Role]
You are an expert summarizer for RFC documents. You specialize in distilling complex technical sections into concise summaries that capture the main points and purpose of each section. You have a deep understanding of RFC structures and can identify key information while omitting unnecessary details.

[Task]
You will be given a section of an RFC document, and you need to generate a concise summary for it. You MUST NOT write any additional text or commentary outside of the summary. You MUST NOT write code to generate the summary. Your summary should capture the main points and purpose of the section.

[Instructions]
- Your summary should capture the main points and purpose of the section.
- The summary should be brief and to the point, in one or two complete sentences.
- Avoid including unnecessary details or examples.
- Include the relation between sections if applicable.
- If the section is empty, return an empty summary.
- If the section only contains a title, you MUST NOT search for external information. Instead, return an empty summary.
- If the section content is empty or only contains formatting characters, return an empty summary.

[Output Format]
You MUST provide your answer in pure json format without any additional text or explanation or code fences. Format:
{
  "summary": "your summary text"
}
      """


def summary_user_prompt(
  section_number: str, section_title: str, section_content: str
) -> str:
  return f"""
Summarize the following RFC section into one or two concise sentences that capture the main points and purpose of the section.
[Input]
1. Section Number: {section_number}
2. Section Title: {section_title}
3. Section Content:

[Output Format]
You MUST provide your answer in pure json format without any additional text or explanation or code fences. Format:
{{
  "summary": "your summary text"
}}
```
{section_content}
```
"""


def split_rough_system_prompt():
  return r"""[ROLE]
You are an expert at reading RFC texts and splitting the texts into very detailed sections based on their semantic relations. You make sure to split the RFC texts clearly and without overlapping each other. For texts that are inside a textually defined section, you will always try your best to give splits of finer granularity. For sections, you ALWAYS give them a section number that can reflect their hierarchy relationships (if they do not have one or their original one does not properly reflect that). You NEVER omit any RFC texts. You also judge if a section should be related to a code implementation or its implementation should be the combination of its sub-sections' implementations. You always try your best to find the root section that can represent the whole RFC text.
[TASK]
You will be given an RFC text. Your job is to give a list of splits, each being a tuple of <Section Name, Section start line number, Section end line number, Should related to implementation>, and a root section index. DO NOT FORGET to give each section a section number. You MUST give your answer in pure json text. JSON format are as follow:

[OUTPUT Format] 
{
  "splits": [
    ["section_name_1", start_line_number_1, end_line_number_1, should_related_to_implementation_1],
    ["section_name_2", start_line_number_2, end_line_number_2, should_related_to_implementation_2],
    ...
  ],
  "root_section": root_section_index
}
"""


def split_rough_user_prompt(rfc_text: str) -> str:
  return f"""
[Input]
{rfc_text}
"""


def pair_hierarchy_system_prompt():
  return r"""[Role]
You are an expert in understanding the structure of technical documents, particularly RFCs (Request for Comments). You specialize in identifying hierarchical relationships between two sections based on their content. You have a deep understanding of how sections in RFCs relate to each other and can accurately determine parent-child relationships. For each pair of sections, you will analyze their content and decide if one section is a parent of the other based on the level of detail and scope covered. You will provide your answer in a clear and structured format.

[Task]
You will be given two sections texts from an RFC document. Your task is to determine if there is a Parent-Child relationship between these two sections based on their content. Specifically, you need to identify which section is the parent and which is the child, if such a relationship exists.

[Instructions]:
Identify the Parent-Child relationship between the two sections. A Parent-Child relationship exists when one section provides a detailed breakdown of another, establishing a clear hierarchical link.
Example: If Section 1 outlines the general header format and Section 2 delves into a specific header field, then Section 1 is the Parent to Section 2.

[Output Format]:
You MUST provide your answer in PURE json format WITHOUT any additional text or explanation or code fences. Format:
{
  "relationship": ["parent_section_number", "child_section_number"] or []
}
"""


def pair_hierarchy_user_prompt(
  section1: str,
  section2: str,
) -> str:
  return f"""
[Input]
Section 1:
{section1}
Section 2:
{section2}
"""


def hierarchy_system_prompt():
  return r"""
[Role]
You are an expert in understanding the structure of technical documents, particularly RFCs (Request for Comments).

[Task]
You will be given a list of sections texts from an RFC document. Your task is to determine the hierarchical relationships between these sections based on their content. Specifically, you need to identify which sections are parents and which are children. You MUST provide your answer in a clear and structured format (see Output Format). You MUST NOT write any additional text or commentary outside of the specified output format. You MUST NOT write code to generate the output.

[Example]:
1. ICMPv6 General Message Format (Section 2) is the Parent of ICMPv6 Error Messages (Section 3), and ICMPv6 Informational Messages (Section 4), because ICMPv6 Message Header outlines the general header format, while the other sections delve into specific message types that use this header format. For such cases, you will output:
{
  "hierarchies": [["2", "3"], ["2", "4"], ...]
}

2. BABEL have Section 4.3 describing the TLV general format, and Section 4.4 describing sub-TLV general format, with Section 4.6 describing specific TLVs and Section 4.7 describing specific sub-TLVs. In this case, Section 4.3 is the Parent of Section 4.6, and Section 4.4 is the Parent of and Section 4.7. Also you will find Section 4.2 which describes the general packet format, and Section 4.3 describing TLV format is a part of the packet format. In this case, Section 4.2 is the Parent of Section 4.3. Additionally, BABEL has Section 4.1.3 (Router-Id) describing the router-id data model concept (an arbitrary 8-octet value that MUST NOT be all zeroes or all ones), which should be a child of Section 4.6.7 (Router-Id TLV) since the TLV section is the concrete implementation that carries the router-id value. Section 4.1.4 (Address) describes address encodings (AE 0-3), and should be a child of every section that uses address/address encodings: Section 4.6.6 (IHU), Section 4.6.8 (Next Hop), Section 4.6.9 (Update), Section 4.6.10 (Route Request), and Section 4.6.11 (Seqno Request). That is:
{
  "hierarchies": [["4.6.7", "4.1.3"], ["4.6.6", "4.1.4"], ["4.6.8", "4.1.4"], ["4.6.9", "4.1.4"], ["4.6.10", "4.1.4"], ["4.6.11", "4.1.4"], ["4.2", "4.3"], ["4.2", "4.4"], ["4.3", "4.6"], ["4.4", "4.7"], ...]
}


[Instructions]:
Identify the Parent-Child relationships among sections. A Parent-Child relationship exists when one section provides a detailed breakdown of another, establishing a clear hierarchical link.
Example: If Section 1 outlines the general header format and Section 2 delves into a specific header field, then Section 1 is the Parent to Section 2.

[Output Format]:
You MUST provide your answer in PURE json format WITHOUT any additional text or explanation or code fences. Format:
{
  "hierarchies": [["parent_section_number", "child_section_number"], ...]
}
    """


def hierarchy_user_prompt(
  sections: "list[Any]",  # pyright: ignore[reportExplicitAny]
) -> str:
  section_texts = "\n\n".join(
    [f"Section {s.number}: {s.title}\n\n{s.summary}" for s in sections]  # pyright: ignore[reportAny]
  )
  section_texts = f"""
Given the following sections from an RFC document, identify the Parent-Child relationships among them. A Parent-Child relationship exists when one section provides a detailed breakdown of another, establishing a clear hierarchical link. You MUST provide your answer in PURE json format WITHOUT any additional text or explanation or code fences. Format:
{{
  "hierarchies": [["parent_section_number", "child_section_number"], ...]
}}  

[Example]:
1. ICMPv6 General Message Format (Section 2) is the Parent of ICMPv6 Error Messages (Section 3), and ICMPv6 Informational Messages (Section 4), because ICMPv6 Message Header outlines the general header format, while the other sections delve into specific message types that use this header format. For such cases, you will output:
{{
  "hierarchies": [["2", "3"], ["2", "4"], ...]
}}

2. BABEL have Section 4.3 describing the TLV general format, and Section 4.4 describing sub-TLV general format, with Section 4.6 describing specific TLVs and Section 4.7 describing specific sub-TLVs. In this case, Section 4.3 is the Parent of Section 4.6, and Section 4.4 is the Parent of and Section 4.7. Also you will find Section 4.2 which describes the general packet format, and Section 4.3 describing TLV format is a part of the packet format. In this case, Section 4.2 is the Parent of Section 4.3. Additionally, BABEL has Section 4.1.3 (Router-Id) describing the router-id data model concept (an arbitrary 8-octet value that MUST NOT be all zeroes or all ones), which should be a child of Section 4.6.7 (Router-Id TLV) since the TLV section is the concrete implementation that carries the router-id value. Section 4.1.4 (Address) describes address encodings (AE 0-3), and should be a child of every section that uses address/address encodings: Section 4.6.6 (IHU), Section 4.6.8 (Next Hop), Section 4.6.9 (Update), Section 4.6.10 (Route Request), and Section 4.6.11 (Seqno Request). That is:
{{
  "hierarchies": [["4.6.7", "4.1.3"], ["4.6.6", "4.1.4"], ["4.6.8", "4.1.4"], ["4.6.9", "4.1.4"], ["4.6.10", "4.1.4"], ["4.6.11", "4.1.4"], ["4.2", "4.3"], ["4.2", "4.4"], ["4.3", "4.6"], ["4.4", "4.7"], ...]
}}


[Instructions]:
Identify the Parent-Child relationships among sections. A Parent-Child relationship exists when one section provides a detailed breakdown of another, establishing a clear hierarchical link.
Example: If Section 1 outlines the general header format and Section 2 delves into a specific header field, then Section 1 is the Parent to Section 2.

[Input]
{section_texts}
"""
  return section_texts
