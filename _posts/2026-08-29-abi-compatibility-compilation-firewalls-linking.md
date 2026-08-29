---
layout: post
title:  "ABI Compatibility, Compilation Firewalls, and Linking"
date:   2026-08-29 08:00:00 +0800
tags: [cpp, abi, linking, compilation-firewalls]
---

* toc
{:toc}

## Three independent questions

Compilation firewalls, linking, and ABI compatibility are related, but they
answer different questions at different stages:

![Compilation, linking, and ABI compatibility are three independent gates](/assets/images/abi_linking_three_questions.png)

| Concern | Question | Primary level |
|---|---|---|
| Compilation firewall | Did a private source change invalidate client compilation inputs? | Source and build dependency |
| Linking | Can referenced symbols be connected to definitions? | Object files and symbols |
| ABI compatibility | Can an already-compiled client safely use this library binary? | Binary contract across versions |

The shortest useful formulation is:

> A compilation firewall makes reusing an old client object file possible.
> ABI compatibility makes reusing that object file correct. Linking connects
> its symbol references, but successful symbol resolution alone does not prove
> ABI compatibility.

## Compilation firewall

A compilation firewall is a source-architecture and dependency-isolation
technique. It prevents private implementation changes from propagating into the
client's compilation inputs.

![The client depends on the public header but not the private implementation header](/assets/images/abi_linking_compilation_firewall.png)

It does **not** mean that the client and library are independent. The client may
still have build-order, symbol, runtime, and behavioral dependencies on the
library. A better descriptive phrase is often *recompilation firewall*.

Typical techniques include incomplete types and PImpl, abstract interfaces,
opaque C handles, forward declarations, minimal public headers, and out-of-line
public functions. The deeper rule is not merely to avoid a file named
implementation header; it is to keep private representation and logic out of
the client's compilation inputs.

For a static library, a private implementation change commonly requires
relinking the executable even though client source files do not recompile:

![A private static-library change requires rebuilding and relinking without recompiling client source](/assets/images/abi_linking_static_library_relink.png)

## Linking and symbol dependency

A compiled client can contain undefined references to public library symbols:

~~~text
client.o:
    U Widget::Widget()
    U Widget::process()
    U Widget::~Widget()

libwidget.so:
    T Widget::Widget()
    T Widget::process()
    T Widget::~Widget()
~~~

For an ordinary executable, required strong symbols normally must be resolved
when it is linked. On ELF/Linux, a shared library may retain some unresolved
symbols to be provided by another shared object, the loading executable, or the
runtime environment. Options such as -Wl,-z,defs can require stricter
resolution while building a shared library.

Deferring symbol resolution does not remove the dependency; it moves resolution
to shared-library load time or, with lazy binding, first use.

Successful linking establishes only that the linker found acceptable symbols
and relocations. It does not prove agreement about C++ layouts, calling
conventions, vtables, ownership, exceptions, or semantics.

## ABI compatibility

ABI compatibility is a binary-substitution assurance between versions:

> Can a client binary built against library version 1 safely use library
> version 2 without recompilation?

![An existing client binary can use a replacement library only when the binary contract remains compatible](/assets/images/abi_linking_binary_substitution.png)

The assurance can depend on exported symbol names and versions, calling
conventions, parameter and return representations, public object size and
alignment, member offsets, vtable and base-class layouts, RTTI and exception
conventions, compiler and standard-library ABI, packing, visibility, allocation,
and ownership across the boundary.

An unchanged header is strong evidence of source-API stability, but it is not
by itself proof about the produced library binary. The compiler configuration,
export map, definitions, and toolchain must also preserve the contract.

## The two properties are independent

### Compilation firewall preserved, ABI compatibility broken

Keep the public header unchanged:

~~~cpp
class Widget {
public:
    Widget();
    ~Widget();
    void process();

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
~~~

If a new library accidentally omits the definition of Widget::process(), the
client's compilation inputs have not changed, so recompiling the client is
unnecessary and would produce the same symbol reference. However, the new
library no longer supplies that public symbol, so linking or loading fails.

![A compilation firewall can remain intact while a replacement library breaks the ABI](/assets/images/abi_linking_firewall_preserved_abi_broken.png)

This is not an ordinary private PImpl layout change; it is the new library
failing to preserve its published binary contract. Other examples include
incompatible compiler ABI settings, changed visibility or symbol versioning, or
different packing and calling-convention options while the header text remains
unchanged.

If a change is truly confined to private PImpl fields or algorithms and the
library continues to honor the same exported ABI, the old client binary should
work. That is the intended safe case.

### Compilation firewall broken, ABI compatibility preserved

Suppose the public header unnecessarily includes the complete implementation
type:

~~~cpp
// widget_impl.hpp
class WidgetImpl {
public:
    int value;
};

// widget.hpp
#include "widget_impl.hpp"

class Widget {
public:
    Widget();
    ~Widget();
    void process();

private:
    WidgetImpl* impl_;
};
~~~

Changing WidgetImpl by adding private state invalidates the transitive
compilation input of every client:

![A leaked private header forces client recompilation even when the public ABI remains compatible](/assets/images/abi_linking_firewall_broken_abi_preserved.png)

But Widget still contains exactly one pointer and its public symbols can remain
unchanged. An existing client binary can therefore remain ABI-compatible with
the new shared library even though the source dependency graph caused an
unnecessary rebuild.

Using a forward declaration repairs the firewall:

~~~cpp
class WidgetImpl;

class Widget {
public:
    Widget();
    ~Widget();
    void process();

private:
    WidgetImpl* impl_;
};
~~~

The complete WidgetImpl definition then belongs only in the library's
implementation file.

### Independence matrix

| Compilation firewall | ABI compatible | Meaning |
|---|---|---|
| Yes | Yes | Desired private implementation change |
| Yes | No | Client object is reusable by the build graph, but unsafe with the new binary |
| No | Yes | Client recompiles unnecessarily, although its old binary would still work |
| No | No | Source changes propagate and existing binaries cannot use the replacement |

## Applying the model to virtual interfaces and PImpl

Virtual interfaces and PImpl share one architectural principle: both put an
indirection boundary between a stable public API/ABI and hidden implementation
details. They are not, however, the same low-level mechanism and they solve
different primary problems:

- A **virtual interface** provides behavioral indirection. A call is dispatched
  according to the object's dynamic type, so different implementations can be
  selected per object at runtime.
- **PImpl** provides representation indirection. A concrete public facade owns
  an opaque pointer to library-private state whose type is normally fixed by the
  library.

Both can be compilation firewalls and both can improve ABI robustness. Object
creation is separated from usage by a factory or a library-defined constructor;
that separation is related to, but not inherently guaranteed by, either kind of
indirection.

### Shared architectural principle

![Virtual interfaces and PImpl place an indirection boundary behind a stable public contract](/assets/images/abi_linking_shared_architecture.png)

In both designs, the client can compile without including implementation
headers. Changes confined behind the public contract therefore normally require
rebuilding the library, but not recompiling the client.

This protection can be weakened by exposing private details through public data
members, inline implementations, templates, third-party types, or unstable
function signatures.

### Virtual interface

~~~cpp
class Transport {
public:
    virtual ~Transport() = default;
    virtual void send() = 0;
};

std::unique_ptr<Transport> create_transport(Protocol protocol);
~~~

The dynamic type of each object determines which implementation receives a
virtual call:

![Virtual dispatch follows the concrete object's vptr and dynamic-type vtable](/assets/images/abi_linking_virtual_dispatch.png)

The important property is runtime substitutability. Different implementations
can coexist in the same process, and the public design may allow clients,
tests, or plugins to provide additional derived classes.

A virtual interface does not itself hide construction. If TcpTransport is
public, a client can construct it directly. Construction becomes library-owned
when the concrete type is hidden and a factory such as create_transport() is
provided. If the client constructs the derived object itself, the construction
site must know the concrete type's construction-facing definition and link to
its constructor and other required concrete symbols. The client consequently
acquires a direct compile-time and link-time dependency on that implementation,
reversing the intended isolation. A provider-owned factory confines the
concrete layout, constructor, dependencies, and allocation policy to the
provider and returns only the abstract interface.

### PImpl

~~~cpp
class Transport {
public:
    Transport();
    ~Transport();
    void send();

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
~~~

The complete implementation exists only in the library source:

~~~cpp
class Transport::Impl {
public:
    void send();
    // Private dependencies and state.
};

void Transport::send() {
    impl_->send();
}
~~~

![PImpl uses an ordinary facade call followed by access through the opaque implementation pointer](/assets/images/abi_linking_pimpl_dispatch.png)

The public Transport is still one concrete type. The opaque pointer hides its
representation and private dependencies, while keeping the facade layout stable
(often one pointer). The pointer normally locates hidden state; it does not
dynamically choose behavior because Transport::Impl is statically known inside
the library.

The client depends on public facade symbols such as Transport::Transport(),
Transport::~Transport(), and Transport::send(). It does **not** normally depend
directly on Transport::Impl symbols. The facade's library object code has that
private dependency.

### Creation and selection

Creation policy is separate from the indirection technique:

![Virtual factories select a derived object while a PImpl constructor creates a hidden representation](/assets/images/abi_linking_creation_selection.png)

For a conventional PImpl, the library defines the private Impl type. Changing
that implementation means rebuilding the library and, for dynamically linked
clients, possibly replacing the shared library while preserving its public ABI.
For static linking, the implementation becomes part of the executable at final
link time; for shared linking, it is resolved when the shared library is loaded.

PImpl can still perform private runtime selection. For example, Impl may own a
TCP, UDP, or vendor-specific backend selected from configuration. The difference
is that this variability remains library-controlled rather than being exposed as
public client-side polymorphism.
