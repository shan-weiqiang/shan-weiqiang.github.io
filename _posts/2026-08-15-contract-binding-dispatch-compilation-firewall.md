---
layout: post
title:  "The Anatomy of a Compilation Firewall"
date:   2026-08-15 09:00:00 +0800
tags: [systems, data-typing]
---

The common architectural principle behind virtual interfaces, type erasure,
PImpl, and dynamically loaded APIs is the separation of behavior-consuming
code from the concrete implementation of that behavior.

This separation consists of three parts:

1. **Contract**: a stable interface describes the operation's arguments,
   result, ownership, lifetime, and error behavior. Across a binary boundary,
   it also includes the ABI: calling convention, symbol identity, and the
   size, alignment, and memory layout of every exposed type used by the
   signature.
2. **Binding**: some provider-side mechanism associates that contract with a
   concrete implementation.
3. **Dispatch**: a call made through the contract is redirected to the bound
   implementation.

In compact form, the consumer compiles against the stable contract while the
binder makes a concrete implementation reachable through indirect dispatch:

![A stable contract and binder machine code create a compilation firewall, while indirect dispatch redirects the consumer's call to the concrete implementation](/assets/images/contract_binding_dispatch_compilation_firewall.png)

Here, **consumer-facing does not mean physically stored in the consumer's
executable**. The consumer always contains its call-site machine code, and a
virtual or function-table call may emit the slot load and indirect-call
instructions there. The associated vtable or invoker can live in a provider
library, however, while a PImpl forwarding method normally lives in the facade
library and dynamic-loader machinery lives in the runtime loader. What these
mechanisms share is the stable boundary seen by the consumer, not one universal
machine-code location.

The **stable contract is what creates the compilation firewall**. A direct,
out-of-line API already lets a provider replace its function bodies without
recompiling the consumer; with an ABI-compatible shared library, that may not
require relinking the consumer either. The second dispatch adds a different
and stronger property: **runtime selection behind one fixed consumer-facing
ABI**. The consumer invokes the common contract. The machine code that realizes
that contract boundary—the binder—uses a vtable slot, erased invoker, resolved
function pointer, or other runtime state to redirect execution to the currently
bound implementation. There is no universal "binder symbol": a PImpl facade
may have a public symbol, while virtual and function-table dispatch can be
implemented directly by instructions emitted at the call site. Nor must there
be two literal machine-level call instructions; "second call" describes the
architectural redirection behind the contract. Changing the selected target
does not change the contract or the consumer's compiled use of it. Indirect
dispatch is therefore not a prerequisite for compile-time isolation itself;
it is the mechanism that permits rebinding or selecting concrete
implementations after the consumer has been compiled. Ordinary PImpl with
fixed, non-virtual forwarding provides the firewall but not this runtime
selection unless another dispatch mechanism is added behind the facade.

The result is a compilation firewall:

```text
Consumer
   |
   | depends only on the stable contract
   v
Binding and indirection boundary
   |
   | redirects the operation
   v
Concrete implementation
```

The consumer must know what operation can be performed and its invocation
contract. For a binary interface, it must also know enough representation to
pass, return, allocate, access, or destroy every exposed value correctly. It
does not need to know the concrete implementation type, its hidden memory
layout, its private dependencies, or the implementation function it will
eventually execute.

* toc
{:toc}

## The binder is machine code

The binder is executable machinery, not merely an architectural relationship.
It associates the common contract with a concrete implementation and makes
that implementation reachable during dispatch.

- For `std::function`, the binder is its library implementation together with
  compiler-generated callable adapters. Construction stores the callable and
  installs its invoker and lifecycle operations.
- For `dlopen()` and `dlsym()`, the binder is the actual dynamic-loader calls
  and loader code that resolve and return a runtime implementation address.
- For virtual functions, the compiler and ABI implicitly generate the binder
  machinery: vtables, vptr initialization, slot loads, and indirect calls.
- For PImpl, programmers handwrite the binder: construction and storage of the
  hidden `Impl` plus forwarding functions that invoke it.

Every binder is therefore concrete code. It either stores an implementation
address in runtime data or encodes the route in a forwarding function. The
contract defines the boundary; binder code constructs and follows its path.

---

## Consumer-side instructions, provider-side data

For runtime-selectable implementations, the division is simpler than it first
appears:

> The consumer contains a fixed sequence of instructions for **how to perform
> the dispatch**. The provider supplies runtime data that determines **which
> concrete implementation those instructions reach**.

The consumer's instructions do not name a concrete type or function. They know
only the stable layout and calling protocol of an object, erased wrapper,
function table, or function pointer. At runtime, the provider passes an
instance of that common representation to the consumer. The consumer reads the
binding information from it and makes the indirect call:

```text
Consumer machine code                 Provider-supplied runtime data
---------------------                 ------------------------------
fixed dispatch instructions    +      object / wrapper / table / address
knows the common ABI                   contains the selected target
             |                                      |
             +---------- indirect call -------------+
                                |
                                v
                    Concrete implementation
```

The same fixed instructions can therefore operate on different runtime values
without recompiling the consumer:

| Mechanism | Provider-supplied data that selects the target |
| --- | --- |
| Virtual function | An object whose vptr selects a vtable and override slot |
| `std::function` | Erased callable storage plus its type-specific invoker pointer |
| Function-table API | A table populated with the selected implementation's addresses |
| `dlsym()` API | A resolved function address selected by library path and symbol name |

Ordinary non-virtual PImpl provides a compilation firewall, but it does not
provide runtime implementation selection.

---

## Virtual functions

An abstract base class defines the contract. Constructing a concrete derived
object binds its virtual-table pointer to the derived class's virtual table. A
virtual call uses the corresponding table entry to reach the concrete
override:

```text
interface pointer -> object vptr -> vtable slot -> concrete override
```

Consumer code compiles against the base interface without knowing the derived
type that will be provided at runtime.

---

## `std::function`

`std::function<R(Args...)>` defines the consumer-visible contract. At the
construction or assignment site, the binder knows the concrete callable type
and installs type-specific invocation and lifecycle operations. Consumer code
only invokes the common signature:

```text
erased callable storage -> invoker function -> concrete callable
```

The translation unit consuming `std::function<R(Args...)>` can therefore be
compiled without knowing the callable type or its implementation. Concrete
callable knowledge is confined to the producer or binding side.

---

## Dynamically loaded APIs

For a dynamically loaded library, the shared header defines a function
signature or API-table layout. `dlopen()` selects and loads a library, while
`dlsym()` resolves a symbol to a runtime function address. Calls then proceed
through that address:

```text
library path -> dlopen -> symbol name -> dlsym -> function pointer -> implementation
```

The client links to the dynamic-loader mechanism and depends on the shared ABI
contract, but it has no direct link-time symbol dependency on the selected
library implementation. The loaded library may additionally return an
abstract interface pointer or function table, producing further indirect
dispatch.

---

## PImpl

PImpl defines a public facade while keeping the `Impl` type incomplete in the
public header. Public methods forward operations to the private implementation:

```cpp
void Component::run()
{
    m_impl->run();
}
```

From the client's architectural point of view, `Component::run()` is the
indirection boundary:

```text
client -> Component::run() -> Component::Impl::run()
```

The client has no source or direct symbol dependency on `Component::Impl` and
can be compiled without its definition. It still links against the public
facade library that defines `Component::run()`. The call from the facade to a
non-virtual `Impl::run()` may be a direct machine instruction, but it occurs
behind the compilation firewall and is invisible to the client.

The opaque pointer is also the representation boundary. The client knows the
layout of the public `Component`, including the fixed handle representation,
but it never sees the size, alignment, or fields of `Component::Impl`.
Changing `Impl` therefore does not change the client's view of `Component`.

---

## The shared principle and the differences

All these mechanisms isolate consumer compilation through a stable boundary,
but they do not necessarily bind implementations at the same time or use the
same machine-level instructions:

| Mechanism | Binding mechanism | Dispatch route |
| --- | --- | --- |
| Virtual interface | Concrete object construction | vptr and vtable |
| `std::function` | Construction or assignment | Erased invoker table |
| `dlopen` API | `dlopen()` and `dlsym()` | Resolved function pointer |
| PImpl | Facade implementation and construction | Public forwarding method and `Impl*` |

Runtime execution of an indirection is not always runtime selection of its
target. Ordinary PImpl normally fixes the forwarding behavior when the facade
library is built, whereas virtual objects, `std::function`, and `dlsym()`
associate implementations using runtime state. Nevertheless, all of them can
provide the compile-time isolation discussed here.

---

## Compilation firewalls do not imply link isolation

A compilation firewall and a link/load boundary answer different questions.
The firewall determines what definitions and private dependencies a consumer
translation unit must see. Normal shared linking determines which symbols and
shared objects must be available when an executable is linked and loaded.

Keep the stages distinct:

```text
compilation:       source + declarations -> object file
static link step:  object files + library metadata -> executable or shared object
dynamic loading:   executable + DT_NEEDED graph -> running process
```

The *static linker* is the build-time link editor even when its inputs include
shared libraries. This does not mean shared-library machine code is copied into
the executable.

With PImpl, a normally linked virtual interface, or type erasure behind a
shared-library API, the consumer can compile without the concrete
implementation. Its object file still normally contains direct undefined
references to public facade or factory symbols, and the executable normally
records the providing library in `DT_NEEDED`:

```text
app
  undefined: Component::run()
  DT_NEEDED: libcomponent.so

libcomponent.so
  defines:   Component::run()
  may need:  private implementation symbols and libraries
```

The implementation library owns its private symbol references. They do not
become direct undefined references of the executable merely because the link
editor inspects or validates the dependency closure. Whether undefined symbols
already present in input shared objects must be satisfied while linking an
executable is toolchain- and option-dependent. GNU-style options such as
`--allow-shlib-undefined`, `--no-allow-shlib-undefined`, and
`--copy-dt-needed-entries` affect validation and dependency propagation.

> Direct public API references are normal link-time dependencies. The runtime
> loader must eventually make the required shared-object graph and processed
> relocations valid, even when the executable link step did not validate the
> entire transitive closure.

For a normally linked `DT_NEEDED` object, the dynamic loader must normally find
and map the object and its dependency graph before `main()`. Eager relocations
must resolve then. Eligible PLT function relocations may be bound lazily on
first call; lazy binding postpones address lookup, not loading of the
`DT_NEEDED` library.

---

## What `dlopen()` and `dlsym()` isolate

`dlopen()` and `dlsym()` provide stronger *build-time and startup dependency
isolation*. If the client has no ordinary reference to a component API symbol,
its executable contains neither an undefined reference to that symbol nor a
`DT_NEEDED` entry for the component library:

```text
executable link:
    resolves dlopen(), dlsym(), and normal client dependencies
    does not inspect or resolve the selected component library

application runtime:
    dlopen(path) invokes the dynamic loader
    the loader maps the component library and its DT_NEEDED closure
    RTLD_NOW resolves required symbols immediately
    RTLD_LAZY may defer eligible function binding
    dlsym(name) returns an entry-point address
```

Thus `dlopen()` does not eliminate the static or dynamic linker altogether.
The client is still linked normally to the loader API where required, and
`dlopen()` explicitly invokes the runtime dynamic loader. It eliminates the
selected component library from the executable's normal link and startup
graph. Loading failure becomes an application-visible result.

---

## Linker checks are not complete ABI checks

Linkers and loaders resolve symbols and validate the metadata required for
relocation, but they do not prove that both sides agree on the complete ABI,
including calling conventions, type layouts, ownership, and lifetime rules.
A matching symbol—or a successful `dlsym()` lookup—therefore does not guarantee
that calling it is ABI-compatible; preserving that contract remains the
responsibility of the programmer and build system.

## Conclusion

A behavioral abstraction exposes a stable contract, confines concrete
implementation knowledge to a binding/provider side, and gives the consumer
an indirect route to that implementation. This boundary acts as a compilation
firewall, allowing the concrete implementation to change without becoming
part of the consumer's compilation dependency, provided the shared contract
remains compatible.
