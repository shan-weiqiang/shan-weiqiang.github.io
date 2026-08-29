---
layout: post
title:  "C++ Compilation Firewalls I"
date:   2026-08-15 09:00:00 +0800
tags: [cpp, compilation-firewalls, type-erasure, abi]
---

This is Part I of the **C++ Compilation Firewalls** series. It explains the
stable contract that separates consumer compilation from implementation and
the additional runtime dispatch used by virtual interfaces, type erasure,
function tables, and dynamically loaded APIs.

A stable binary contract has two complementary meanings:

1. **Stable call contract:** the operation keeps a compatible symbol identity,
   signature, calling convention, ownership model, lifetime rules, and error
   behavior.
2. **Stable data contract:** every type exposed by that operation keeps a
   compatible size, alignment, and memory layout so both sides interpret the
   same bytes in the same way.

Together, these rules create the compilation firewall:

```text
stable call contract + stable exposed data layout
                         = compilation firewall
```

The consumer can compile against that fixed API and ABI without seeing the
concrete implementation, its hidden representation, or its private
dependencies. An ABI-compatible provider can then change its implementation
without requiring consumer recompilation.

PImpl achieves exactly this form of isolation. Its public methods preserve the
call contract, while its opaque pointer gives the public facade a fixed layout
without exposing the layout of `Impl`. The facade may forward to `Impl` using a
normal direct call; runtime indirect dispatch is not required.

Virtual interfaces, type erasure, function tables, and dynamically resolved
APIs add another mechanism on top of the stable contract: **runtime binding and
indirect dispatch**. Runtime data stores or identifies a target, and fixed
dispatch instructions redirect the operation to that target. This makes it
possible to select different concrete implementations at runtime while the
consumer continues to use the same compiled contract.

![A stable API and ABI create a compilation firewall; runtime-dispatch mechanisms additionally select a concrete implementation through binding data](/assets/images/contract_binding_dispatch_compilation_firewall.png)

* toc
{:toc}

## Runtime dispatch machinery is machine code

Runtime binding and dispatch are executable machinery, not merely an
architectural relationship. They associate the common contract with a concrete
implementation and make that implementation reachable at runtime.

- For `std::function`, the binder is its library implementation together with
  compiler-generated callable adapters. Construction stores the callable and
  installs its invoker and lifecycle operations.
- For `dlopen()` and `dlsym()`, the binder is the actual dynamic-loader calls
  and loader code that resolve and return a runtime implementation address.
- For virtual functions, the compiler and ABI implicitly generate the binder
  machinery: vtables, vptr initialization, slot loads, and indirect calls.

This machinery stores an implementation address in runtime data and follows
that address during dispatch. The stable contract creates the compilation
boundary; runtime binding data adds implementation selection behind it. PImpl
needs only the former unless another dispatch mechanism is deliberately added.

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
type that will be provided at runtime. The construction side knows that
concrete type and creates the runtime binding data by initializing the derived
object's vptr. It then passes the object through a base pointer or reference.
The consumer operates on that already-bound object and uses its vptr to select
the override.

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
callable knowledge is confined to the producer or binding side. As with a
derived object, construction creates the runtime binding data: the producer
stores the concrete callable and installs its type-specific invoker and
lifecycle operations inside the `std::function` object. The consumer receives
that already-bound object and invokes it only through `R(Args...)`.

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

All these mechanisms isolate consumer compilation through a stable API and
ABI, but only some add runtime implementation selection:

| Mechanism | Stable contract boundary | Runtime selection and dispatch |
| --- | --- | --- |
| PImpl | Public facade symbols plus fixed opaque-pointer layout | No; forwarding is normally fixed when the facade library is built |
| Virtual interface | Base-class API and compatible object/vtable ABI | Yes; object construction supplies the vptr and vtable |
| `std::function` | Common `R(Args...)` invocation contract and wrapper ABI | Yes; construction installs the erased invoker |
| Function-table API | Fixed table layout and function signatures | Yes; the provider supplies a populated table |
| `dlopen()` API | Shared function signature or API-table ABI | Yes; `dlopen()` and `dlsym()` resolve the runtime target |

The stable contract is the shared compilation-firewall mechanism. Runtime
binding data and indirect dispatch are an additional mechanism used when the
same compiled consumer must select among implementations at runtime.

---

## Compilation firewalls do not imply link isolation

A compilation firewall and a link/load boundary answer different questions.
The firewall determines what definitions and private dependencies a consumer
translation unit must see. Shared linking determines which binary libraries
and symbols must be available when a consumer binary is linked and loaded.

### A shared library is already compiled implementation

A shared library is itself the output of compilation and linking. Its machine
code, exported symbols, private references, and `DT_NEEDED` entries are fixed
when that library is built. An executable or another shared library that uses
it cannot regenerate or specialize that implementation.

### Static linking records direct dependencies

Keep compilation and the build-time link step distinct:

```text
compilation:       source + declarations -> object file
static link step:  object files + library metadata -> executable or shared object
```

The compiler emits object files containing symbol references. The static
linker—the build-time link editor—matches the consumer's direct references
against its link inputs and writes the dynamic symbols, relocations, and
`DT_NEEDED` entries needed for runtime. Using a shared-library input does not
copy that library's machine code into the output binary.

For example, a PImpl client may compile without `Component::Impl`, but it still
refers to the public facade and normally records its provider:

```text
app
  undefined: Component::run()
  DT_NEEDED: libcomponent.so

libcomponent.so
  defines:   Component::run()
  may need:  private implementation symbols and libraries
```

The link editor resolves or records the output's direct symbol requirements.
Whether it also validates undefined symbols already contained in dependent
shared libraries—and whether transitive dependencies are copied into the
output's own dependency list—is toolchain- and option-dependent. GNU-style
options such as `--allow-shlib-undefined`, `--no-allow-shlib-undefined`, and
`--copy-dt-needed-entries` control this validation and propagation. Inspecting
a dependency's symbols does not make them direct undefined references of the
consumer; those references remain owned by the shared library that contains
them.

### Runtime loading follows `DT_NEEDED` transitively

At startup, the dynamic loader follows the executable's `DT_NEEDED` entries
and then the `DT_NEEDED` entries of those libraries. This dependency graph must
normally be found and mapped before control enters `main()`:

```text
executable
    -> direct DT_NEEDED libraries
        -> their DT_NEEDED libraries
            -> complete mapped startup dependency graph
```

Required eager relocations are resolved during loading. Eligible PLT function
relocations may instead resolve lazily when first called. Lazy symbol binding
postpones lookup of a function address; it does not postpone loading the
normally linked `DT_NEEDED` library that supplies it.

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

A compilation firewall exposes a stable call contract and stable layouts for
the data that crosses it, while keeping concrete implementation knowledge on
the provider side. PImpl provides this isolation through a fixed facade and
opaque representation without requiring runtime dispatch. Virtual interfaces,
type erasure, function tables, and dynamically loaded APIs preserve the same
kind of contract while additionally using runtime binding data and indirect
dispatch to select a concrete implementation.
