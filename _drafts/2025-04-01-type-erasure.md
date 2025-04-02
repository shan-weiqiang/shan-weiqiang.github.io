- all polymorphism(might be except pimpl) in c++ comes from two language features: template and virtual inheritance
- template is compile time polymorphism and can only be used at compile time
- virtual inheritance is runtime polymorphism and can be used at runtime
- one design pattern can be actualized both in compile time and runtime
- external polymorphism is combination of compile time and runtime polymorphism
  - at compile time, not only pass the type, but also pass the operation
  - but even with virtual inheritance and abstract interface, the user still need to know the type of the base abstract class: concrete types are erased, but not the base interface type
- type erasure is combination of external polymorphism and pimpl. type erasure types are not template types
  - make the virtual inheritance abstract base class internal and use a pimpl to point to it
  - after type erasion, to the user there is only one non-template type interface with template constructor, after construction, there is no type information inside this type anymore(memory wise)
  - ​Type erasure is external polymorphism made generic and seamless.
- std::function is a set of type erasure types, with each template signature a individual type erasure types:
  - the template parameter is compile time polymorphism and can accept callable signature at compile time
  - after the compile time polymorphism, the signature is determinied, it is instantiated to a type erasure type; at runtime, std::function object can be bound to any callable time that conforms to this signature
  - as a result, the std::function itself can accept any signature at compile time and any callable object that is of the same signature type
 
```cpp
#include <cstdlib>

// Following code are in *.cpp file, without Some exposed
// But user will call this code through type erased interface: void
// print_data(const void *p). This is the core of type erasure: encapsulate type
// infomation in implementation, remove type information in interface.
struct Some {
  int data;
};
bool less(const void *l, const void *r) {
  return static_cast<const Some *>(l)->data <
         static_cast<const Some *>(r)->data;
}

// The declaration in *.h, exposed to external user
// ! Here is where the type erasure happens
bool less(const void *, const void *);

// User of type erasure: qsort does not need to know which type it will sort,
// type is erased from qsort: type erasure is an abstraction for multiple
// implementations that provide the same behavior, the relevent behavior is what
// matters, not the type. In this example, `compare` parameter requires that two
// elements can be compared, qsort does not care about how it is compared, as
// long as it return a bool value. This gives chances to implement the compare
// logic in source code, instead of in interface code.

// Since type erasure is about abstraction of behavior, it alwarys involve
// redirection of function pointers, no matter which way it is implemented.

// Compared with C, C++ ONLY add implementation methods for type erasure. In C,
// we have to manually write different implementations, like the `less` and
// `more` function in below. In C++, we have the compiler to generate different
// implementation code for us. They all involves template and are done at
// construction phase. The three ways are:
// 1. virtual inheritance: redirection hanppens when using base class pointer to
// call implementation in derived class(whose type is erased)
// 2. static templated functions: C++ compiler will generate
// code implementation for each template instantiation. It's the same as C, but
// code generated instead of manually written. Note that generated static
// functions are class members, which means that the amount of instantiations
// equals the number of generated class member functions.
// 3. vtable: Similar as 2, this time use a vtable to point to instead of
// generating static class member functions.

// One more important fact is that all the C++ ways are of value semantics. The
// implementation is stored as value(function pointers can be seen as value of
// function variables).
void qsort(void *base, size_t nmeb, size_t size,
           bool (*compare)(const void *, const void *));

// Following give another type that also use qsort
struct Tome {
  int data;
};
bool more(const void *l, const void *r) {
  return static_cast<const Tome *>(l)->data <
         static_cast<const Tome *>(r)->data;
}
bool more(const void *, const void *);

int main() {
  Some a[10];
  Tome b[10];
  // qsort is universal, thanks to the redirection of `compare` parameter
  qsort(a, 10, 4, less);
  qsort(b, 10, 4, more);
}
```
