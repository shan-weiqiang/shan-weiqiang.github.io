---
layout: post
title: "PImpl, Virtual Interfaces, and Function Tables"
date: 2026-10-11 09:00:00 +0800
tags: [cpp, pimpl, polymorphism, linking, abi]
---

PImpl, virtual interfaces, and function tables all separate client code from implementation details. **The essential difference is where the call target comes from.** Conventional PImpl calls a named wrapper function whose implementation uses a particular `Impl`. A virtual call obtains its target from the supplied object's virtual table; a function-table call obtains it from supplied function pointers. Those runtime values let the same consumer call different concrete implementations without naming their symbols.

* toc
{:toc}

## Comparison

| Aspect | Conventional PImpl | Virtual interface | Function table |
|---|---|---|---|
| Compilation separation | Hides private representation behind an opaque pointer | Hides concrete classes behind a base interface | Hides concrete functions behind function pointers, usually with an opaque context |
| Call target in the consumer | Named wrapper function symbol | Virtual-table entry reached through the supplied object | Function pointer read from the supplied table |
| Link-time dependency of the consumer | Depends on wrapper symbols, which transitively depend on the concrete implementation | Calls through the interface require no concrete implementation symbols | Calls through the table require no concrete implementation symbols |
| **Implementation selection** | **Determined by the implementation library linked or loaded** | **Determined by the derived-class instance supplied at runtime** | **Determined by the function pointers supplied at runtime** |
| **Switching implementations** | **Normally requires linking another implementation library or replacing a compatible shared library** | **Supply a different derived-class instance within the same running program** | **Supply a different function table within the same running program** |

Here, "conventional PImpl" means a wrapper whose implementation uses a particular concrete Impl type, without an additional runtime dispatch mechanism. "No link-time dependency" means no dependency on a *particular concrete implementation*, not an absence of all symbols or libraries.

## 1. Compilation separation

An ordinary function declaration already separates the client from the function body:

```cpp
void run();
```

The client needs the declaration, not the definition. Changing the function body normally does not require recompiling the client.

Classes introduce an additional concern: clients may need the class's size and layout to allocate it or embed it in another object. Private members still affect that layout.

PImpl moves the changing private representation behind an opaque pointer:

```cpp
class Widget {
public:
    Widget();
    ~Widget();
    void run();
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
```

The constructor, destructor, and operations are defined out of line, where Impl is complete. Changes to Impl's members do not change the wrapper's layout.

Thus, PImpl extends the familiar declaration/definition boundary to a class's private representation. Plain out-of-line member functions alone do not hide changes to member layout.

Virtual interfaces and function tables also allow concrete implementations to change without recompiling consumers, provided their client-facing contracts remain compatible.

## 2. Link-time decoupling

### Conventional PImpl

The dependency chain is:

```text
client -> named wrapper symbol -> wrapper code -> particular Impl
```

The client normally does not reference Impl symbols directly. It still references the wrapper's functions. The wrapper depends on the concrete implementation, so that dependency must be satisfied when the wrapper is linked or loaded. PImpl alone does not let the consumer select a different implementation by supplying a runtime object or function table.

### Virtual interfaces and function tables

The consumer uses call targets carried by runtime values:

```text
virtual interface: client -> object -> virtual-table slot -> concrete function
function table:    client -> table entry               -> concrete function
```

The consumer knows the slot or table-field layout, but does not name the concrete function in its call. It can compile and link without the derived-class implementation or the functions that will eventually populate a table. A direct call also has a runtime address, but its target is identified by a symbol that must be resolved during linking or loading; the address is not an implementation-selection value supplied to the consumer.

This property applies to the interface-consuming code, not automatically to the entire executable. Something must construct the derived object or populate the function table. Direct construction, a direct factory call, or taking concrete function addresses introduces dependencies in that supplying code. A host or runtime plugin loader can provide implementations across a separate boundary.

## 3. Implementation selection: the central distinction

With conventional PImpl, the wrapper is built with a particular implementation. Once the implementation library is selected through linking or loading, the consumer does not choose another implementation merely by passing different runtime data. Switching normally requires relinking against another implementation library or replacing a compatible shared library.

Virtual interfaces and function tables make implementation selection part of the runtime calling arrangement:

- **Virtual interface:** pass different derived-class instances to the same compiled consumer.
- **Function table:** pass different sets of function pointers, typically paired with implementation-specific context, to the same compiled consumer.

Multiple implementations can therefore coexist and be selected within one running program without rebuilding or relinking the consumer.

PImpl can internally use a virtual interface, a function table, or another selection mechanism. In that case, runtime selection comes from the added mechanism, not from the opaque pointer itself.

## 4. Recompilation versus relinking

Avoiding client recompilation does not necessarily avoid relinking. Updating a statically linked implementation generally requires relinking the executable. Replacing a shared library can avoid rebuilding the executable if binary compatibility is preserved.

None of these techniques automatically guarantees binary compatibility after arbitrary changes to the public contract.
