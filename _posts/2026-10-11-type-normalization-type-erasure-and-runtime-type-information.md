---
layout: post
title: "Type Normalization, Erasure, and RTTI"
date: 2026-10-11 09:00:00 +0800
tags: [cpp, type-erasure, rtti, polymorphism]
---

* toc
{:toc}

## Type normalization and the erased boundary

Here, **type normalization** means converting pointers to different object types into a common `void*` representation. This basic form of type erasure hides the static pointee type from the consumer without changing the object itself. Other erased representations include a virtual interface or a wrapper with bound callbacks.

The `void*` conversion alone only hides the type. To use an erased instance, the design must bind it to compatible operations: functions that accept the erased representation and know how to act on the underlying object.

## Binding erased instances to operations

The purpose of type erasure is to let a consumer work without depending on the specific concrete type. This has two dimensions: the representation of the instance itself, and the operations available on that instance. An opaque instance alone is of limited use unless the consumer also has a way to do something with it, even if that only means storing it and returning it later.

With a virtual interface, the interface API already specifies the available operations, and virtual dispatch connects each call to an implementation compatible with the object. When implementing type erasure by hand, the designer must establish the corresponding binding between the erased instance and compatible operations. Maintaining that binding is one of the key implementation responsibilities: a function pointer with the right signature is not necessarily valid for every erased instance.

A runtime type identifier can help manage this binding. It might be an enumeration value, an agreed string name, or another token identifying the underlying type or a supported category. Such identifiers are useful, but are not mandatory: a wrapper can instead package the instance together with its matching callbacks or operation table when it is created.

To simplify the discussion, consider an operation to be a function that accepts an erased instance. There are then two scopes to consider:

1. **The consumer managing instances and operations.** It holds erased instances and function pointers, and may use a runtime type ID to look up a compatible operation in a registry. The providers can register those operations without requiring the consumer to name the concrete C++ types.
2. **The implementation of an operation.** A type-specific implementation knows the concrete type it supports. Its job is to restore typed access to the erased instance, typically by casting the opaque pointer back to that type, and then perform the operation. If a single entry point supports several concrete types, it may use a runtime type ID to select the appropriate cast and implementation. A dedicated callback for one type usually needs no runtime type ID because its binding to the instance already establishes which type to expect.

The consumer can therefore use runtime identifiers to bind instances to operations without acquiring compile-time or link-time dependencies on the concrete C++ types. The implementation or adapter retains the concrete-type knowledge needed to access the object. This is the value of the identifier at the consumer boundary: it makes runtime distinctions available without requiring the consumer to name the types themselves. The consumer still depends on the meaning of the IDs and the operation contract.

An ID does not by itself make access to the object valid. If a branch casts the instance to a concrete type or calls its members directly, that branch does depend on that type; such knowledge must live in the appropriate implementation or adapter. If it only selects compatible callbacks using agreed IDs, it can remain independent of the concrete types. In either design, the instance, identifier, and operations must remain consistent, and the object must remain alive during use. Retaining a runtime ID does not undo type erasure at the consumer's interface.

### Questions for an erased interface

The instance–operation contract gives us three related questions to ask about an erased interface:

1. **Consumer dependencies:** Can the consumer hold the instance and request its supported operations without naming the concrete C++ type?
2. **Operation binding:** How does the design ensure that each erased instance reaches a compatible implementation—through a virtual interface, bound callbacks, or an ID-based lookup?
3. **Runtime identity:** Is a type ID retained, who uses it, and does that use merely select operations or require knowledge of concrete C++ types?

## RTTI is not an inverse of type erasure

Type erasure hides a type across an interface. RTTI permits certain runtime type inspections when suitable information remains available. These mechanisms can coexist: hiding a type from the consumer does not require discarding its identity everywhere.

A bare `void*` does not provide a way to discover the original pointee type. `typeid(ptr)` for a `void*` reports the pointer's static type; dereferencing a `void*` to inspect its object is not available.

To retain runtime type information in a hand-written `void*`-based design, the user must associate the pointer with a type ID, typically by grouping them in the same structure. The ID records which type the erased pointer represents and must remain consistent with it. This information is explicitly retained alongside the pointer; it cannot be recovered from the `void*` alone.

### dynamic_cast through a virtual interface

Given a polymorphic base, a checked downcast can test whether an object supports a particular derived-class relationship:

```cpp
struct Base {
    virtual ~Base() = default;
    virtual void run() = 0;
};
struct A : Base {
    void run() override;
    void specialOperation();
};
void client(Base& obj) {
    if (auto* a = dynamic_cast<A*>(&obj)) {
        a->specialOperation();
    }
}
```

For this downcast, the source provides a polymorphic interface and the target class must be complete. A failed pointer cast returns null; a failed reference cast throws `std::bad_cast`.

The client now knows `A`, creating a compile-time dependency and potentially dependencies on its RTTI and operation symbols at link time. Calling `obj.run()` would instead use the common operation contract and leave concrete-type knowledge in the derived implementation. A successful `dynamic_cast<A*>` does not necessarily mean the most-derived type is exactly `A`; an object further derived from `A` can also satisfy the cast.

Using `dynamic_cast<A*>` makes the consumer depend on a specific type again, working against the concrete-type independence offered by the virtual interface. However, it does not remove all the interface's benefits:

1. Other clients can continue to use only the virtual interface without performing any downcasts.
2. A client that downcasts to `A` need not know every other concrete implementation.
3. Even for `A`, the client may need a downcast only on specific occasions. Its ordinary operations can still use the virtual interface, keeping implementation details behind that interface despite the concrete-type and possible link dependencies introduced by the cast.
4. Link decoupling is only one possible benefit of a virtual interface. A common operation contract, interchangeable implementations, and shared client logic remain useful even when some concrete-type dependencies exist.

### typeid, type_info, and type_index

`typeid` yields a `const std::type_info&`. For an expression designating an object of polymorphic class type, it can report the dynamic type; otherwise it reports the static type according to the language rules.

`std::type_index` wraps `std::type_info` to make type identities convenient to compare and use as associative-container keys. It does not recover type information from an opaque pointer, cast that pointer, or supply operations on the object.

Like `dynamic_cast`, `typeid` participates in C++'s RTTI facilities. Checking against `typeid(A)` requires naming the specific type `A`, just as `dynamic_cast<A*>` does. When the consumer performs either check, it acquires a dependency on that concrete type. Their operations differ: `dynamic_cast` checks a class relationship and performs a conversion, while comparing type identities does not convert or validate an erased pointer.

An erased reference can explicitly retain its original static type:

```cpp
#include <typeindex>
struct ErasedRef {
    void* ptr;
    std::type_index type;
};
template<class T>
ErasedRef erase(T& obj) {
    return {static_cast<void*>(&obj), std::type_index(typeid(T))};
}
```

This simple helper is intended for mutable, non-volatile objects that remain alive throughout use. The pointer and metadata must remain consistent.

An implementation that knows `A` can then branch and restore typed access:

```cpp
void process(ErasedRef obj) {
    if (obj.type == std::type_index(typeid(A))) {
        auto& a = *static_cast<A*>(obj.ptr);
        a.specialOperation();
    }
}
```

Here, the information was **captured before erasure and retained alongside the pointer**, not recovered from `void*`. The cast is justified by the helper's pointer/tag contract, not checked by `std::type_index`.

This helper deliberately uses `typeid(T)`: if called with a `Base&`, it records `Base`. Merely replacing it with dynamic `typeid(obj)` can label a base-subobject pointer with a derived type without adjusting the pointer appropriately, invalidating a later direct cast from `void*` to that derived type.

At the abstraction boundary, this is a manual counterpart to `dynamic_cast`: check retained type information, then restore typed access. It has the same dependency tradeoffs when used by the consumer. Comparing against `typeid(A)` and casting to `A*` reintroduces knowledge of `A`, along with possible link dependencies, but does not remove all the benefits of the erased interface. Other consumers can remain independent of `A`; this consumer need not know every concrete type or use typed access for every operation. Common operations can still hide implementation details, and link decoupling remains only one benefit of the abstraction. Unlike `dynamic_cast`, however, this manual scheme relies on the pointer/tag contract to justify the cast; it does not perform a checked class-hierarchy conversion.

## Application-defined identifiers and factories

An application-defined string such as `"image"` can name an implementation without naming its C++ type. The name can select a factory; the resulting object must still carry or expose compatible operations.

### Virtual interface and factory registry

A registry can map an identifier to a factory that returns the common virtual interface. Registration knows the concrete class; the consumer only uses the identifier and interface:

```cpp
#include <memory>
#include <string>
#include <unordered_map>

struct Renderer {
    virtual ~Renderer() = default;
    virtual void render() const = 0;
};

using RendererFactory = std::unique_ptr<Renderer> (*)();
using RendererRegistry = std::unordered_map<std::string, RendererFactory>;

struct ImageRenderer final : Renderer {
    void render() const override { /* render an image */ }
};

// Provider code: knows ImageRenderer.
void register_image(RendererRegistry& registry) {
    registry.emplace("image", +[]() -> std::unique_ptr<Renderer> {
        return std::make_unique<ImageRenderer>();
    });
}

// Consumer code: needs only Renderer, RendererRegistry, and "image".
void use_renderer(const RendererRegistry& registry) {
    auto renderer = registry.at("image")();
    renderer->render();
}
```

The factory selects construction. Once it returns the object, virtual dispatch binds `render()` to that object's implementation; the consumer does not inspect the identifier before every call. The registry name is an application contract, while the class definition remains provider-side.

### Hand-written type erasure and factory registry

A hand-written wrapper can carry an opaque `void*`, an identifier, and the operations bound to that instance. The operation table below includes creation, destruction, and rendering. `std::unique_ptr` invokes the matching deleter, so the wrapper owns its erased object:

```cpp
#include <memory>
#include <string>
#include <unordered_map>

struct Erased {
    using Deleter = void (*)(void*) noexcept;

    struct Operations {
        void* (*create)();
        Deleter destroy;
        void (*render)(const void*);
    };

    std::string id;
    Operations operations;
    std::unique_ptr<void, Deleter> object;
};

struct Image {
    void render() const { /* render an image */ }
};

// Provider code: creates the object and binds operations for Image.
Erased make_image() {
    const Erased::Operations operations{
        []() -> void* { return std::make_unique<Image>().release(); },
        [](void* ptr) noexcept {
            std::unique_ptr<Image> owned{static_cast<Image*>(ptr)};
        },
        [](const void* ptr) { static_cast<const Image*>(ptr)->render(); }
    };
    return {"image", operations,
            {operations.create(), operations.destroy}};
}

using ErasedFactory = Erased (*)();
using ErasedRegistry = std::unordered_map<std::string, ErasedFactory>;

void register_image(ErasedRegistry& registry) {
    registry.emplace("image", &make_image);
}

// Consumer code: needs no Image declaration or cast.
void use_erased(const ErasedRegistry& registry) {
    auto value = registry.at("image")();
    value.operations.render(value.object.get());
}
```

The wrapper's `object`, `id`, deleter, creator, and `render` operation form one contract. The provider must keep the pointer and operations compatible. The registry maps an identifier to a factory for constructing that package; the consumer invokes the bound operation without recovering the C++ type. A different design could register operation tables by identifier instead of storing a table in every wrapper.

### What the identifier does not provide

An identifier alone provides neither a valid cast nor an operation. A consumer that knows a concrete type can branch on a retained ID and cast an opaque pointer, but the ID does not check that cast:

```cpp
if (value.id == "image") {
    auto& image = *static_cast<Image*>(value.object.get());
    image.render();
}
```

This branch must include `Image` and trust that the pointer, ID, and lifetime agree. With a polymorphic base pointer, `dynamic_cast<ImageRenderer*>` can instead check a supported class relationship. Comparing `typeid(*renderer)` with `typeid(ImageRenderer)` identifies a type but does not convert the pointer. Both approaches name the concrete type in the consumer.

The factory examples take the other path: `"image"` selects construction, and the returned virtual interface or erased wrapper supplies compatible operations. **The ID selects a provider; the interface or bound callbacks make the instance usable.** The consumer still depends on the identifier's agreed meaning and the operation contract, but need not depend on the concrete C++ class.

## Creation, use, and optional concrete-type inspection

The same three stages apply to a virtual interface and a hand-written erased wrapper:

1. **Create by identifier.** An ID such as `"image"` selects one of several factory function pointers with the same signature. This is runtime selection among values, not a separate type-erasure boundary. The selected factory returns a base-interface object or erased wrapper that hides the concrete type. The ID names a registered implementation or category, not necessarily an exact C++ type.
2. **Use the common API.** The consumer invokes operations through the virtual interface or the hand-written operation table. Neither path needs a concrete class name. The object and its operations were bound together during creation.
3. **Inspect the concrete type only when needed.** A consumer that needs a concrete-only operation must cross the erased boundary. With a polymorphic base, it can use `dynamic_cast<Concrete*>` for a checked class conversion, or `typeid` to inspect dynamic type identity before a separate conversion. With an opaque `void*`, it cannot apply `dynamic_cast` directly; it needs retained type information or a trustworthy ID–pointer contract before casting back to a concrete pointer. In either design, naming `Concrete` in the consumer introduces a concrete-type dependency.

The factory ID is sufficient to select construction, and the common API is sufficient for ordinary use. Neither requires the consumer to recover the concrete C++ type. Concrete inspection is an optional, more tightly coupled path; an ID or `typeid` result alone does not provide typed access.
