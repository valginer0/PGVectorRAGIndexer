# PEP 701 Implementation in Black PR #3822

## High-Level Explanation of the Implementation

### What PEP 701 Changed

PEP 701 formalized f-string syntax in Python 3.12, lifting restrictions that existed since their introduction in Python 3.6. The key changes allowed quote reuse, backslashes in expressions, multi-line expressions, and comments inside f-strings.

### The Core Problem

Previously, Black's tokenizer treated f-strings as single STRING tokens (e.g., `f"foo{2 + 2}bar"` was one token). This couldn't handle the new PEP 701 syntax where nested f-strings could reuse quotes.

### The Implementation Approach

#### Token Decomposition

The implementation breaks f-strings into component tokens:
- **FSTRING_START**: The opening `f"`
- **FSTRING_MIDDLE**: Literal string parts
- **LBRACE/RBRACE**: Expression delimiters
- **FSTRING_END**: Closing quote

For example, `f"foo{2 + 2}bar"` is now tokenized as:

```
FSTRING_START('f"')
FSTRING_MIDDLE('foo')
LBRACE('{')
NUMBER('2')
OP('+')
NUMBER('2')
RBRACE('}')
FSTRING_MIDDLE('bar')
FSTRING_END('"')
```

#### Recursive Tokenization

The key architectural decision was making the tokenizer recursive. When the tokenizer encounters an f-string, it calls `generate_tokens()` recursively to tokenize the Python expressions inside the curly braces. This allows proper handling of arbitrarily nested f-strings.

#### Stack-Based Quote Tracking

Rather than using a simple counter, the implementation uses a stack to track quote delimiters at different nesting levels. When entering a new f-string context, the quote type is pushed onto the stack; when exiting, it's popped. This allows the tokenizer to correctly identify where one f-string ends and another begins, even when they use the same quote characters.

#### Expression Parsing

Inside the `{...}` braces, the tokenizer treats the content as regular Python code, recursively tokenizing it with the full Python grammar. This naturally handles complex expressions, nested f-strings, backslashes, comments, and multi-line content.

### Benefits

The implementation enables Black to parse and format the new f-string syntax while maintaining backward compatibility with older f-strings, all by leveraging the existing tokenization infrastructure in a recursive manner rather than requiring special-case string parsing logic.

## Examples of New Capabilities

**Quote Reuse:**
```python
# Now valid in Python 3.12
f"outer {"inner"}"
```

**Backslashes in Expressions:**
```python
# Now valid in Python 3.12
f"path: {'\n'.join(paths)}"
```

**Multi-line Expressions:**
```python
# Now valid in Python 3.12
f"""result: {
    compute_value()  # with comments
}"""
```

## Technical Impact

By decomposing f-strings into individual tokens and using recursive tokenization with stack-based quote tracking, Black can now:

1. Parse all valid Python 3.12 f-string syntax
2. Maintain backward compatibility with older f-strings
3. Provide better error messages with precise location information
4. Enable future f-string formatting improvements in preview mode

---

*This explanation is based on Black PR #3822 and PEP 701 documentation.*
