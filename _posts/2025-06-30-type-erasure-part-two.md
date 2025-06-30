---
layout: post
title:  "Type Erasure Part Two: How std::function Works"
date:   2025-06-29 10:00:00 +0800
tags: [c++]
---

std::function Implementation:

---

**Inherits `_Function_base`** to get the storage, responsible for data, itself contains `_M_invoker`:
- **`_M_functor`**: A union structure that stores actual callable, might be pointer or heap allocated callable objects. The `_M_init_functor` will move `__f`, the callable to be stored in `_M_functor`
- **`_M_manager`**: A function pointer in `_Function_handler` to create/destroy/... the `_M_functor`
- **`_M_invoker`**: A function pointer in `_Function_handler` to call the callable
- **`&_My_handler::_M_invoke`/`&_My_handler::_M_manager`**: Static functions bound with `_Functor` type providing clone/destroy operations, which operates on the stored callable object. So the stored callable must be compatible with those static function pointers, which is done during construction.

---

**Points to `_Function_handler` type** that do the type erasure of the passed actual callable type, responsible for code

---

After construction, the binding is fixed to a specific `_functor`, aka user callable. Even though `std::function`'s type is only determined by callable signature, `_Function_handler`'s type is also determined by the actual callable type that is passed by user during construction.

---

The binding between data and code is done at construction phase at compile time. If we assign a `std::function` variable to another instance, the data and code must be both changed at the same time, which is done during run time (using the `swap(...)` member function). This data and code binding pattern happens for all methods of implementing type erasure:

- **Virtual classes** are bound to their vtable during compile time
- **Statically generated template functions** (or user written functions implementing type erasure) bind data and code at compile time

This data and code binding during compile time is at the core of how type erasure works, since only after the binding, type can be erased.

![std::function Implementation](/assets/images/std_function.png)
