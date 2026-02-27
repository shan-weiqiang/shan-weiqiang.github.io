# Data Format Compatibility: Protobuf vs JSON

---

# 1️⃣ Protocol Buffers Compatibility Characteristics

## Core Principle

Protocol Buffers achieves forward and backward compatibility by encoding
data using **field numbers (tags)** instead of field names. The binary
wire format stores:

    (field_number, wire_type, value)

Field names do NOT exist in serialized data.

Compatibility is therefore determined by:
    Stable field numbers + stable wire types

---

## ✅ Forward Compatibility

Old code can read data produced by a newer schema.

- Unknown fields are safely skipped.
- Known fields are parsed normally.
- No parsing error occurs.

Reason:
Each field carries its tag number and wire type.
If a tag is unknown, the parser deterministically skips it.

---

## ✅ Backward Compatibility

New code can read data produced by an older schema.

- Missing fields are assigned default values.
- Existing fields parse normally.

Reason:
If a field number is absent in the binary data,
the parser initializes the field with its defined default value.

---

## ✅ Safe Schema Changes

These changes preserve compatibility:

- Add a new field with a new field number
- Remove a field (never reuse its number)
- Rename a field (keep same number)
- Add new enum values
- Add optional fields

Reason:
Wire format is defined by field number + wire type only.
If those remain stable, compatibility remains stable.

---

## ❌ Unsafe Changes (Breaking)

These changes break compatibility:

- Changing a field number
- Changing a field’s wire type (e.g., int32 → string)
- Reusing a deleted field number
- Changing required ↔ optional (proto2)

Reason:
Binary layout changes, leading to misinterpretation of data.

---

## Why Protobuf Compatibility Is Reliable

1. Numeric tags instead of names
2. Self-describing binary fields
3. Deterministic unknown-field skipping
4. Deterministic defaulting rules
5. Compatibility rules defined at protocol level

Compatibility is engineered into the encoding itself.

---

# 2️⃣ JSON Compatibility Characteristics

## Core Principle

JSON is a text-based data format with:

- String keys
- Dynamic typing
- No built-in schema
- No defined compatibility rules

Compatibility is NOT defined by JSON itself.
It depends entirely on the parser and application logic.

---

## Case A: Fully Dynamic Parsing

Example (Python / JavaScript style):

    data = json.loads(...)
    age = data.get("age")

Characteristics:

- Unknown fields are naturally ignored unless accessed
- Missing fields return null / undefined / default via logic
- No compile-time enforcement

Result:

Compatibility is flexible but informal.
There is no strict compatibility contract.

---

## Case B: Static / Structured Parsing

Example (C++ struct / Java class / Rust struct):

    struct Person {
        std::string name;
        int age;
    };

Behavior depends on the JSON library:

- May ignore unknown fields
- May reject unknown fields
- May require certain fields
- May provide defaults
- May throw on type mismatch

Compatibility becomes implementation-specific.
