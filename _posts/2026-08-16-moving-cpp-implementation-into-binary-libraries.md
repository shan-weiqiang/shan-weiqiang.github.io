---
layout: post
title:  "C++ Compilation Firewalls II"
date:   2026-08-16 09:00:00 +0800
tags: [cpp, compilation-firewalls, templates, shared-libraries]
---

This is Part II of the **C++ Compilation Firewalls** series and a sequel to
[Part I: Stable Contracts and Runtime
Dispatch](/2026/08/15/contract-binding-dispatch-compilation-firewall.html).
Part I examined the stable API and ABI between a consumer and an
implementation. This article asks a practical follow-up question: **how much
C++ implementation can be moved out of public headers and compiled into a
binary library?**

* toc
{:toc}

## The technical rule

A function can be compiled into a binary library when the library compiler has
all information required to generate its machine code.

A definition must remain visible to the consumer's compiler when that compiler
must generate a new specialization or perform compile-time evaluation using
information supplied by the consumer.

The central cause of this boundary is unknown compile-time information,
especially consumer-provided types. If all relevant types and operations are
known when the library is built, the implementation can be compiled into the
binary. If a future consumer type changes the code that must be generated, the
type-dependent definition must remain visible to the consumer. Non-type
template arguments and consumer-side constant evaluation follow the same rule,
so unknown types are the main case rather than the only case.

## Code-generation ownership

The unifying question is:

> Who owns the information required to generate this machine code?

Compilation-firewall techniques separate that ownership:

- **PImpl:** the library owns the private representation and generates all code
  that uses `Impl`; the consumer knows only the public facade.
- **Virtual interface:** the caller owns only the abstract contract, while each
  provider owns and compiles its concrete override.
- **Type erasure:** a type-specific adapter maps each concrete `T` operation to
  one common function signature. The binary core can therefore express its
  logic once through that uniform contract instead of generating different
  logic for every `T`.
- **Explicit instantiation:** the library owns the closed set of supported
  types and generates their specializations.
- **Public templates:** the consumer owns future types, so it must generate the
  corresponding specializations from visible definitions.
- **`dlopen()` and `dlsym()`:** the client compiler knows the ABI contract,
  while runtime loading code supplies the implementation library and symbol
  address later.

These mechanisms do not eliminate concrete information. They confine it to the
side that owns it and replace it across the boundary with a stable contract.
Once concrete type knowledge is no longer needed, the remaining implementation
can be compiled independently into the binary.

## Pushing the boundary toward the consumer

The architectural goal is to keep only the irreducibly type-dependent binding
code on the consumer side. Once that code converts the unknown type into a
stable contract, the larger type-independent implementation can be generated
by the library compiler and stored in the shared library.

![Consumer-owned type-dependent adaptation crosses a stable contract into a type-independent shared-library core](/assets/images/cpp_binary_library_compilation_boundary.png)

Moving the stable boundary toward the consumer makes the header-side adapter
smaller and the precompiled binary region larger. The mechanisms have distinct
roles: normalization and type erasure remove the core's need to know a
consumer-provided type; virtual interfaces provide a fixed runtime operation
set; PImpl hides library-owned state; and explicit instantiation lets the
library own a closed set of specializations.

## Code that can be in a binary library

### Non-template functions

A non-template function can be compiled separately when its parameter, return,
and referenced types are sufficiently defined while building the library:

```cpp
// Header
Result process(BufferView input);

// Source compiled into the library
Result process(BufferView input)
{
    return processImpl(input);
}
```

The consumer needs the declaration. It does not need the definition.

### Code using runtime-polymorphic types

The concrete runtime type may be unknown. The code can still be precompiled if
the compiler knows a fixed interface:

```cpp
Result process(Input& input);       // Virtual interface
Result process(ErasedInput input);  // Type-erased interface
Result process(InputHandle input);  // Opaque handle
```

The binary implementation is generated against the known interface. Runtime
dispatch selects the concrete operation later.

### Templates with a closed instantiation set

Template definitions can be private to the library when the library explicitly
instantiates every supported specialization:

```cpp
// Public declaration
template<class T>
Result process(T);

extern template Result process<int>(int);
extern template Result process<double>(double);
```

The library defines the template and emits `process<int>` and
`process<double>`. Consumers cannot instantiate an additional type unless the
definition is also made visible.

### Internal templates

Templates used only by library source files can remain private. Being a
template does not itself require a public header; only consumer-side
instantiation does.

## Code that must be visible to the consumer

### Open template instantiation

If consumers may instantiate a template with arbitrary future types, its
definition must normally be reachable at the point of instantiation:

```cpp
template<class T>
auto process(T&& value)
{
    return value.execute();
}
```

The library could not precompile `process<UserType>` before `UserType`
existed.

### Type-dependent compile-time operations

A definition must be visible when consumer compilation needs properties such
as:

- `sizeof(T)` or `alignof(T)`.
- Construction, destruction, or layout of arbitrary `T`.
- Overload resolution and expressions involving arbitrary `T`.
- A result type computed from consumer-provided types.
- Constant evaluation performed in the consumer translation unit.

### Inline definitions required in multiple translation units

An `inline` function may be header-defined even when it is not a template.
This is allowed distribution, not proof that the code cannot exist in a
binary. If the public API only declares an out-of-line version, that version
can instead be compiled into the library.

## Moving the technical boundary

Code initially written as a public template may be divided into two parts:

```text
consumer-type-dependent adaptation
                |
                v
fixed representation or operation table
                |
                v
type-independent compiled implementation
```

Only the first part must remain visible.

### Fixed representation

Normalize many input types to one known type:

```cpp
template<class Range>
Result process(const Range& range)
{
    return processBytes(std::as_bytes(std::span(range)));
}

Result processBytes(std::span<const std::byte> bytes);
```

The adapter is instantiated by the consumer. `processBytes` is compiled once
in the binary.

In the broad architectural sense, this can be viewed as a special kind of type
erasure: **representation erasure**. Different concrete range types are reduced
to the same `std::span<const std::byte>` boundary type, so they all share the
same `processBytes` implementation. The consumer still instantiates the small
`process<Range>` conversion adapter for each `Range`, but the library does not
instantiate a different main implementation for every source type. This
differs from behavioral type erasure, which preserves type-specific behavior
through different per-type adapters that all expose the same operation
signature.

### Virtual interface

A virtual base class gives the binary a known operation set while allowing
runtime concrete types:

```cpp
Result process(Input& input);
```

### Type erasure

Type erasure converts type-specific operations into a common signature. The
small adapter still depends on `T`, but it presents every supported type to the
binary core through the same fixed interface:

```cpp
template<class T>
ErasedInput eraseInput(T&& input);

Result process(ErasedInput input);
```

The library can therefore compile the main algorithm once against
`ErasedInput`. At runtime, the adapter redirects each uniform operation to the
corresponding operation for the stored `T`. The adapter remains type-dependent;
the library's code logic becomes type-independent.

### PImpl

PImpl addresses the opposite direction. It hides library-owned concrete state
from the consumer:

```text
consumer knows PublicType
library knows PublicType and PublicType::Impl
```

Public method definitions and all operations on `Impl` can be compiled into
the binary. PImpl does not erase consumer-provided types and does not by itself
move arbitrary public template instantiations into the library.

## Conclusion

> Know the contract completely; know the consumer's concrete types as little
> as possible.

From the library developer's perspective, the central architectural task is to
define a stable API using fixed, library-known boundary types and operations.
Consumer-specific representations should be normalized, adapted, erased, or
kept behind an interface before control enters the compiled core. PImpl hides
library-owned implementation types, while `dlopen()` and `dlsym()` can also
defer selection of the implementation library until runtime.

The intended dependency direction is:

```text
consumer concrete types -> stable contract <- shared-library implementation
```

Once the library no longer requires consumer-specific compile-time
information, its type-independent algorithms, state, and lifecycle code can be
generated by the library compiler and stored in the shared library. Only the
irreducibly consumer-type-dependent adapter or specialization must remain
visible.
