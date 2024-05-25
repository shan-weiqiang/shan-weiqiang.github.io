---
layout: post
title:  "pimpl vs virtual class: binary difference"
date:   2024-05-25 10:22:46 +0800
tags: [C++]
---


Both pimpl and pure abstract class can achieve compile firewall, but they are different in theory and used in different scenarios in real world

### Technical difference under the hood

#### pimpl

The core of pimpl is opaque pointer. The user only know the public APIs plus opaque pointer. During compiling time, the user code can complile without knowing the implementation details of the object that the opaque pointer points to, because the memory size is known to the user(pointer size is known for the user). Note: whether the user is shared lib or executable, there is no need for recompile or relink needed when the client side changes, because the user side do not need to compile and link will be done during runtime by dynamic linker of the os. The user side even can write a dummy implementation for the client APIs for the purpose of debuging and isolation of working with the client side and there are no needs for recompile or link when the dummy implementation lib is replaced with the real client lib. The development for user side and client side can be isolated this way. The core reason why pimpl works is the dynamic linker, which can reallocate symbols during runtime.

There is additional method to achieve more efficiency, such as `lazy binding` in the process of dynamic linking.

Note: no additional CPU instructions are generated for using pimpl, overhead comes from the pointer access of the opaque pointer.

#### pure abstract class

Pure abstract class use virtual table as the media to achieve compile isolation. It's a process called `late binding`

Late binding, also known as dynamic binding or runtime binding, refers to the process of determining the specific function implementation to be called at runtime, based on the actual type of the object being referred to. It is typically associated with polymorphism and virtual function dispatch.

In languages like C++, when a virtual function is called on a pointer or reference to a base class, late binding ensures that the appropriate function implementation is selected based on the runtime type of the object. This allows different derived classes to have their own implementations of the same virtual function, providing flexibility and extensibility.

Note: The user use the base pure virtual class and the APIs and when the user's code are actually executed, the API implementation is decided by the actual derived subclasses that is passed into the user's function. At compile time the user's code only knows the base class and will generate the CPU instructions for how to get relevent function address based on the virtual table, but at runtime, the passed instance is subclass of base class, which has a different virtual table address(but the instrunctions for finding functions are the same); This way the functions found is the implementation of the subclass. This behavior decides that if the base class's member or methods are changed (whether it's quantity or appearance squences, because these all influence the CPU instructions generated from the compiler), the user code need to be compiled again, while pimpl do not have this problem.

The overhead of pure abstract class is in the access of the virtual tables.

Note that pure abstract class does not prevent successuful building even if there are no implementations:

```c++
#include <iostream>

class VirtualClass {
public:
  virtual void f() = 0;
};

void somefunc(VirtualClass *cls) {
  std::cout << "Hello" << std::endl;
  /// This call be compiled successfully, but will have segmentation fault at
  /// runtime
  cls->f();
}

int main() {
  void *ptr;
  somefunc((VirtualClass *)(ptr));
}
```

Above code will compile successfully!

### Use case

Pure abstract class is mainly used as interface. Namely, a group of clients has the same API and the user side only need to use the common interfaces that are shared by all the clients. It's one to more mapping between the user and the client. The actualization is achieved by passing different client instances into the user.

Pimpl is mainly used for encapsulation. Namely, a class or lib is exposed to user as standard APIs(only public api that will be used by user) and the private implementations are hidden by the opaque pointer. It's more to one mapping between user and client. The actualization is achieved by user use the standard API provided by client and link to the client lib.

### Compile fire wall and linking

Compile isolation means there is no need for `static` recompiling and relinking during compilation time, only runtime dynamic linking(pimpl) or runtime virtual table handling(pure abstract class) is required for the client's new implementation to take effect.