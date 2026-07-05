---
layout: post
title:  "Double Dispatch and the Visitor Pattern in C++"
date:   2026-07-04 10:01:00 +0800
tags: [cpp]
---

Double dispatch is the technique C++ uses to pick the right behavior when **two** object types matter at runtime — for example, which print routine runs for a `Circle` on an `InkjetPrinter` vs a `LaserPrinter`. This post walks through the Visitor pattern step by step, using one shape hierarchy and concrete, compilable code at every stage.

* toc
{:toc}

# Overview: two dispatches, one operation

When a client calls `shape.accept(printer)`, two runtime decisions happen in sequence:

1. **First dispatch** — virtual `accept` on the shape picks the concrete type (`Circle`, `Rectangle`, …).
2. **Second dispatch** — the shape calls `printer.printCircle(*this)` (or `printRectangle`, …), which resolves to the concrete printer override (`InkjetPrinter`, `LaserPrinter`, …).

![Double dispatch sequence diagram: visited hierarchy (Shape/Circle/Rectangle), visitor hierarchy (Visitor/AreaVisitor/CollisionVisitor), and accept → visitCircle flow](/assets/images/cpp_double_dispatch_flow.png)

The rest of this post builds that mechanism from scratch.

# Step 1 — The problem: single dispatch is not enough

Suppose we want to **print** shapes (`Circle`, `Rectangle`) on different **printers** (`InkjetPrinter`, `LaserPrinter`). The correct routine depends on **both** runtime types — shape and printer. C++ virtual functions alone only give **single dispatch**: one virtual call resolves the type of **one** object.

## Single dispatch: only the printer type varies

If every call site already holds a `Circle&`, a single virtual on `Printer` is enough — only the printer is polymorphic:

```cpp
#include <iostream>

class Circle {
public:
  explicit Circle(double radius) : radius_(radius) {}
  double radius() const { return radius_; }

private:
  double radius_;
};

class Printer {
public:
  virtual void printCircle(Circle& c) = 0;
  virtual ~Printer() = default;
};

class InkjetPrinter : public Printer {
  void printCircle(Circle& c) override {
    std::cout << "Inkjet: circle r=" << c.radius() << '\n';
  }
};

class LaserPrinter : public Printer {
  void printCircle(Circle& c) override {
    std::cout << "Laser: circle r=" << c.radius() << '\n';
  }
};

int main() {
  Circle c{3.0};
  InkjetPrinter inkjet;
  LaserPrinter laser;

  Printer* p1 = &inkjet;
  Printer* p2 = &laser;
  p1->printCircle(c);  // Inkjet — one runtime dispatch on printer
  p2->printCircle(c);  // Laser
}
```

```text
Inkjet: circle r=3
Laser: circle r=3
```

The shape type (`Circle`) is fixed at compile time. The vtable picks `InkjetPrinter::printCircle` vs `LaserPrinter::printCircle`. That is single dispatch on the printer.

## Two shape types: one virtual `print(Shape&)` is not enough

Add `Rectangle` as a second shape and store shapes as `Shape&`. Each shape calls into the printer via `accept`, but a naive `Printer` exposes only one method for all shapes:

```cpp
class Shape {
public:
  virtual void accept(Printer& p) = 0;
  virtual ~Shape() = default;
};

class Circle : public Shape {
public:
  explicit Circle(double radius) : radius_(radius) {}
  double radius() const { return radius_; }
  void accept(Printer& p) override { p.print(*this); }

private:
  double radius_;
};

class Rectangle : public Shape {
public:
  Rectangle(double w, double h) : width_(w), height_(h) {}
  double width() const { return width_; }
  double height() const { return height_; }
  void accept(Printer& p) override { p.print(*this); }

private:
  double width_, height_;
};

class Printer {
public:
  virtual void print(Shape& shape) = 0;  // single method for all shapes
};

class InkjetPrinter : public Printer {
  void print(Shape& shape) override {
    // Need Inkjet×Circle vs Inkjet×Rectangle logic.
    // But `shape` is Shape& — compiler does not know which shape.
    // dynamic_cast<Circle*>(&shape)? Fragile and scatters logic.
  }
};
```

```cpp
Circle c{3.0};
Rectangle r{4.0, 5.0};
InkjetPrinter inkjet;

c.accept(inkjet);
r.accept(inkjet);
```

The **first** dispatch works: `c.accept(inkjet)` resolves to `Circle::accept`. But `p.print(*this)` always calls `print(Shape&)` — the compiler never sees `Circle&` or `Rectangle&` inside `InkjetPrinter`. We need a **second** dispatch that passes the shape's **concrete type** into the printer.

## What double dispatch gives us (preview)

Give `Printer` one virtual method **per shape type**. Each shape's `accept` calls the matching one; `InkjetPrinter` and `LaserPrinter` override both:

```cpp
class Printer {
public:
  virtual void printCircle(Circle& c) = 0;
  virtual void printRectangle(Rectangle& r) = 0;
  virtual ~Printer() = default;
};

class Circle : public Shape {
public:
  explicit Circle(double radius) : radius_(radius) {}
  double radius() const { return radius_; }
  void accept(Printer& p) override {
    p.printCircle(*this);  // passes Circle& — second dispatch via printer vtable
  }

private:
  double radius_;
};

class Rectangle : public Shape {
public:
  Rectangle(double w, double h) : width_(w), height_(h) {}
  double width() const { return width_; }
  double height() const { return height_; }
  void accept(Printer& p) override {
    p.printRectangle(*this);  // passes Rectangle&
  }

private:
  double width_, height_;
};

class InkjetPrinter : public Printer {
  void printCircle(Circle& c) override {
    std::cout << "Inkjet: circle r=" << c.radius() << '\n';
  }
  void printRectangle(Rectangle& r) override {
    std::cout << "Inkjet: rectangle " << r.width() << 'x' << r.height() << '\n';
  }
};

class LaserPrinter : public Printer {
  void printCircle(Circle& c) override {
    std::cout << "Laser: circle r=" << c.radius() << '\n';
  }
  void printRectangle(Rectangle& r) override {
    std::cout << "Laser: rectangle " << r.width() << 'x' << r.height() << '\n';
  }
};
```

```cpp
Circle c{3.0};
Rectangle r{4.0, 5.0};
InkjetPrinter inkjet;
LaserPrinter laser;

c.accept(inkjet);  // 1st: Circle::accept  2nd: InkjetPrinter::printCircle
r.accept(laser);   // 1st: Rectangle::accept  2nd: LaserPrinter::printRectangle
```

```text
Inkjet: circle r=3
Laser: rectangle 4x5
```

Inside `InkjetPrinter::printCircle`, both types are known: the shape is `Circle&` and the printer is `InkjetPrinter`. The same pattern generalizes to a `Visitor` base with `visitCircle` / `visitRectangle` in the steps below.

# Step 2 — The visited side: `accept()` is the entrance

Every visited class must implement `accept(Visitor&)`. In best practice, `accept` is a **pure virtual** method on the base class so no concrete shape can forget it.

## Visited hierarchy

Forward-declare `Visitor` (defined in the next step):

```cpp
#include <iostream>

class Visitor;  // forward declaration

class Shape {
public:
  virtual ~Shape() = default;
  virtual void accept(Visitor& v) = 0;  // pure virtual — enforces contract
};

class Circle : public Shape {
public:
  explicit Circle(double radius) : radius_(radius) {}
  double radius() const { return radius_; }
  void accept(Visitor& v) override;

private:
  double radius_;
};

class Rectangle : public Shape {
public:
  Rectangle(double w, double h) : width_(w), height_(h) {}
  double width() const { return width_; }
  double height() const { return height_; }
  void accept(Visitor& v) override;

private:
  double width_, height_;
};
```

## `accept` implementations

Each derived class calls the matching method on the visitor, passing **its own concrete type**:

```cpp
void Circle::accept(Visitor& v) { v.visitCircle(*this); }
void Rectangle::accept(Visitor& v) { v.visitRectangle(*this); }
```

**Note:** `accept` is always the entrance on the visited side. Client code starts double dispatch by calling `shape.accept(visitor)`, never by calling `visitXxx` on the visitor directly (unless both types are already known — covered in Step 8).

## Best practice: pure virtual `accept` catches missing implementations

If a new derived class forgets to override `accept`:

```cpp
class Triangle : public Shape {
  // forgot accept()
};

int main() {
  Triangle t;  // error: abstract type
}
```

```text
error: cannot declare variable 't' to be of abstract type 'Triangle'
note: because the following virtual functions are pure within 'Triangle':
note:   virtual void Shape::accept(Visitor&)
```

The compiler enforces that every concrete visited class participates in the protocol.

# Step 3 — The visitor side: one `visitXxx` per visited type

The visitor base class declares a `visitXxx` method for **every** visited type. Each concrete visitor implements all of them. Inside a `visitXxx` override, the compiler knows **both** the visitor subclass and the visited type — that is where application logic belongs.

## First complete program: `AreaVisitor`

```cpp
#include <iostream>

class Visitor;

class Shape {
public:
  virtual ~Shape() = default;
  virtual void accept(Visitor& v) = 0;
};

class Circle : public Shape {
public:
  explicit Circle(double radius) : radius_(radius) {}
  double radius() const { return radius_; }
  void accept(Visitor& v) override;

private:
  double radius_;
};

class Rectangle : public Shape {
public:
  Rectangle(double w, double h) : width_(w), height_(h) {}
  double width() const { return width_; }
  double height() const { return height_; }
  void accept(Visitor& v) override;

private:
  double width_, height_;
};

class Visitor {
public:
  virtual ~Visitor() = default;
  virtual void visitCircle(Circle& c) = 0;
  virtual void visitRectangle(Rectangle& r) = 0;
};

void Circle::accept(Visitor& v) { v.visitCircle(*this); }
void Rectangle::accept(Visitor& v) { v.visitRectangle(*this); }

class AreaVisitor : public Visitor {
public:
  void visitCircle(Circle& c) override {
    // HERE: dynamic type of *this is AreaVisitor
    // HERE: static type of c is Circle&
    // => implement Circle × Area logic in one place
    std::cout << "Circle area: " << 3.14159 * c.radius() * c.radius() << '\n';
  }
  void visitRectangle(Rectangle& r) override {
    std::cout << "Rectangle area: " << r.width() * r.height() << '\n';
  }
};

int main() {
  Circle c{3.0};
  Rectangle r{4.0, 5.0};
  AreaVisitor av;
  c.accept(av);
  r.accept(av);
}
```

```text
Circle area: 28.2743
Rectangle area: 20
```

## Extensibility cost

The Visitor pattern trades **two different extensibility axes**:

**Adding a new visited type** (e.g. `Triangle : Shape`) ripples through the whole protocol:

```cpp
// Adding Triangle : Shape requires:
//   1. Triangle::accept       -> v.visitTriangle(*this)
//   2. Visitor::visitTriangle (pure virtual on base)
//   3. AreaVisitor::visitTriangle, PrintVisitor::visitTriangle, ...  (every existing visitor)
```

**Adding a new operation** (e.g. `PrintVisitor : Visitor`) only requires a **new visitor class** that implements every `visitXxx` already declared on the visitor base. The visited side does **not** change — `Circle::accept` still calls `v.visitCircle(*this)`; `Rectangle::accept` still calls `v.visitRectangle(*this)`. Those `accept` implementations are fixed when the hierarchy is wired up; they dispatch through the `Visitor&` vtable to whichever concrete visitor you pass in.

```cpp
class PrintVisitor : public Visitor {
public:
  void visitCircle(Circle& c) override { /* print circle */ }
  void visitRectangle(Rectangle& r) override { /* print rectangle */ }
};

// No edits to Circle::accept, Rectangle::accept, or Shape — just use the new visitor:
c.accept(PrintVisitor{});
```

This trade-off favors a **stable class hierarchy** with **many operations** — compilers, ASTs, scene graphs. Adding a new shape type is expensive; adding a new pass or renderer is cheap.

# Step 4 — Optional `visit()` sugar on the visitor

The visitor may provide a convenience helper that forwards to `accept`. This is syntactic sugar only; **`accept` on the visited object remains the canonical entrance**.

```cpp
class Visitor {
public:
  virtual ~Visitor() = default;
  virtual void visitCircle(Circle& c) = 0;
  virtual void visitRectangle(Rectangle& r) = 0;

  void visit(Shape& s) { s.accept(*this); }  // sugar — not the pattern's entry point
};

int main() {
  Circle c{1.0};
  Rectangle r{2.0, 3.0};
  AreaVisitor av;
  c.accept(av);   // canonical: entrance on visited object
  av.visit(r);    // equivalent sugar — ends up in r.accept(av)
}
```

Both styles produce the same output:

```text
Circle area: 3.14159
Rectangle area: 6
```

**Note:** Prefer `shape.accept(visitor)` in APIs that define the visited hierarchy. The `visit(Shape&)` helper is optional ergonomics for call sites that hold a visitor and want to pass shapes in reverse order.

# Step 5 — Partial visitors: compile-time checks and intentional no-ops

With a fat visitor base (Step 3), every concrete visitor must implement **all** `visitXxx` methods declared on the base. That is enforced at **compile time**: an incomplete visitor is an **abstract class** and cannot be instantiated. Step 5 also covers two other valid partial designs — no-op defaults and a base that **omits** some `visitXxx` APIs — where excluded shape types are never visited, again with compile-time checks.

## Compile-time check: incomplete visitor is abstract

If `Visitor` keeps `visitRectangle` pure virtual, a visitor that only handles circles does not compile:

```cpp
class PrintCircleOnlyVisitor : public Visitor {
public:
  void visitCircle(Circle& c) override {
    std::cout << "Circle r=" << c.radius() << '\n';
  }
  // missing visitRectangle — class stays abstract
};

int main() {
  PrintCircleOnlyVisitor pv;  // error: abstract type
}
```

```text
error: cannot declare variable 'pv' to be of abstract type 'PrintCircleOnlyVisitor'
note: because the following virtual functions are pure within 'PrintCircleOnlyVisitor':
note:   virtual void Visitor::visitRectangle(Rectangle&)
```

This is a **feature** of the strict design: the type system refuses a half-implemented visitor. Every `accept` ↔ `visitXxx` pair on the base must have a real override in every concrete visitor you construct.

## When you want partial behavior: no-op defaults (intentional design)

Sometimes a visitor **should** only do work for some shape types; for others, doing nothing is correct. That is not an error — it is a **deliberate API choice**. Provide empty default implementations on the visitor base instead of pure virtual for the pairs you want to opt out of:

```cpp
class PartialVisitor {
public:
  virtual ~PartialVisitor() = default;
  virtual void visitCircle(Circle& c) = 0;       // must implement — circles matter
  virtual void visitRectangle(Rectangle&) {}     // default no-op — rectangles optional
};

class PrintCircleOnlyVisitor : public PartialVisitor {
public:
  void visitCircle(Circle& c) override {
    std::cout << "Circle r=" << c.radius() << '\n';
  }
  // visitRectangle inherits empty default — intentional
};

int main() {
  Circle c{2.0};
  Rectangle r{1.0, 1.0};
  PrintCircleOnlyVisitor pv;

  c.accept(pv);  // prints
  r.accept(pv);  // calls inherited no-op — valid if that is what you designed
}
```

Here `Rectangle::accept` still calls `v.visitRectangle(*this)`; the empty base implementation runs. That is **by design**, not silent failure — you chose a base where unhandled pairs are no-ops. Document which visitors handle which shapes, same as you would document any other API contract.

## When the base omits `visitXxx` entirely

You can also define a **narrower visitor base** that declares only the `visitXxx` methods you need — and **leave others out** of the API altogether. Shapes outside that protocol are simply never visited through it; that is still a valid, compile-time-checked design.

```cpp
class CircleOnlyVisitor {
public:
  virtual ~CircleOnlyVisitor() = default;
  virtual void visitCircle(Circle& c) = 0;
  // no visitRectangle — not part of this protocol
};

class Circle : public Shape {
public:
  // ...
  void accept(CircleOnlyVisitor& v) { v.visitCircle(*this); }
};

class Rectangle : public Shape {
public:
  // ...
  void accept(Visitor& v) override { v.visitRectangle(*this); }  // full Visitor only
  // no accept(CircleOnlyVisitor&) — rectangles never enter the circle-only protocol
};

class PrintCircleOnlyVisitor : public CircleOnlyVisitor {
public:
  void visitCircle(Circle& c) override {
    std::cout << "Circle r=" << c.radius() << '\n';
  }
};

int main() {
  Circle c{2.0};
  Rectangle r{1.0, 1.0};
  PrintCircleOnlyVisitor pv;

  c.accept(pv);   // OK — double dispatch runs
  // r.accept(pv);  // compile error — Rectangle has no accept(CircleOnlyVisitor&)
}
```

If you try to wire a shape into a protocol the base does not support, the compiler fails immediately — same as Style B in Step 6:

```cpp
void Rectangle::accept(CircleOnlyVisitor& v) {
  v.visitRectangle(*this);  // error: CircleOnlyVisitor has no member named visitRectangle
}
```

So a missing `visitXxx` on the base means **that node is outside this visitor API** — it will never be reached via `accept` on that base type. No runtime surprise: either the shape has no matching `accept` overload, or the `accept` body names a method the base does not declare. All of it is resolved at compile time.

### The visitor base API is the type contract

As long as the visitor base declares the correct `visitXxx` signatures and each shape's `accept` calls the matching method with `*this`, **the pairing cannot go wrong at the `visitXxx` call**. The compiler checks every link:

```cpp
class CircleOnlyVisitor {
public:
  virtual ~CircleOnlyVisitor() = default;
  virtual void visitCircle(Circle& c) = 0;
  // no visitRectangle — not part of this protocol
};

void Circle::accept(CircleOnlyVisitor& v) {
  v.visitCircle(*this);  // *this is Circle& — only visitCircle(Circle&) applies
}
```

```text
Circle::accept(v)
  → v.visitCircle(*this)
      *this static type: Circle&     ✓ matches visitCircle(Circle&)
      cannot become Rectangle&      ✗ no conversion, no wrong overload
```

There is **no path** through `accept` that passes a `Rectangle&` into `visitCircle(Circle&)` or calls a `visitXxx` the base does not declare. Style B names each method explicitly (`visitCircle`, not overloaded `visit(Shape&)`), so the visited type and the visitor parameter type are **locked together at compile time**. Wrong wiring is a compile error; wrong runtime instance types at `visitXxx` are not possible once the API is correct.

That is why partial and narrow visitor bases remain safe: the protocol you define in the base class **is** the type system the compiler enforces — not a convention you hope call sites follow at runtime.

## Choosing between the three

| Base design | Incomplete concrete visitor | Shape not in protocol |
| --- | --- | --- |
| Pure virtual every `visitXxx` on fat base | **Compile error** — cannot instantiate | N/A — all wired shapes must have matching `visitXxx` |
| Default no-op for some `visitXxx` | **Compiles** — missing overrides inherit no-op | All wired shapes call `accept`; unhandled pairs run no-op |
| `visitXxx` **omitted** from base | Concrete visitor implements only declared methods | **Never visited** — no `accept` overload or compile error if mis-wired |

**Recommendation:** use pure virtual `visitXxx` on the main `Visitor` base when every operation must handle every shape (Style B in Step 6). Introduce no-op defaults on a **separate** base (e.g. `PartialVisitor`) only when partial behavior is an explicit product requirement. Use a **narrow base** that omits `visitXxx` when entire shape types should not participate in that protocol at all — still compile-time safe, with those nodes simply never visited.

Both strict and partial designs keep wrong **visitor class definitions** and wrong **wiring** visible at compile time (abstract type, missing member, or missing `accept` overload). With a correct base API, there is also **no wrong argument type at `visitXxx`** through the `accept` path — `*this` and the method parameter type are fixed together. The difference is whether unhandled shapes are forbidden, no-ops, or excluded from the API entirely.

# Step 6 — Two styles of visitor API: overloaded `visit()` vs named `visitXxx()`

There are two common ways to name the visitor methods. Both achieve double dispatch; they differ in clarity and safety.

## Style A — uniform `visit()` with overloads

Same `Circle` / `Rectangle` as before; `accept` calls overloaded `visit`:

```cpp
#include <iostream>

class OverloadVisitor;

class Circle {
public:
  explicit Circle(double radius) : radius_(radius) {}
  double radius() const { return radius_; }
  void accept(OverloadVisitor& v);

private:
  double radius_;
};

class Rectangle {
public:
  Rectangle(double w, double h) : width_(w), height_(h) {}
  double width() const { return width_; }
  double height() const { return height_; }
  void accept(OverloadVisitor& v);

private:
  double width_, height_;
};

class OverloadVisitor {
public:
  virtual ~OverloadVisitor() = default;
  virtual void visit(Circle& c) = 0;
  virtual void visit(Rectangle& r) = 0;
};

void Circle::accept(OverloadVisitor& v) { v.visit(*this); }
void Rectangle::accept(OverloadVisitor& v) { v.visit(*this); }

class AreaOverloadVisitor : public OverloadVisitor {
public:
  void visit(Circle& c) override {
    std::cout << "Circle area: " << 3.14159 * c.radius() * c.radius() << '\n';
  }
  void visit(Rectangle& r) override {
    std::cout << "Rectangle area: " << r.width() * r.height() << '\n';
  }
};

int main() {
  Circle c{3.0};
  Rectangle r{4.0, 5.0};
  AreaOverloadVisitor av;
  c.accept(av);
  r.accept(av);
}
```

`Circle::accept` calls `v.visit(*this)`; overload resolution picks `visit(Circle&)` because `*this` is a `Circle&`.

## Style B — named `visitXxx()` (recommended)

Identical `main()`, different visitor API surface:

```cpp
#include <iostream>

class NamedVisitor;

class Circle {
public:
  explicit Circle(double radius) : radius_(radius) {}
  double radius() const { return radius_; }
  void accept(NamedVisitor& v);

private:
  double radius_;
};

class Rectangle {
public:
  Rectangle(double w, double h) : width_(w), height_(h) {}
  double width() const { return width_; }
  double height() const { return height_; }
  void accept(NamedVisitor& v);

private:
  double width_, height_;
};

class NamedVisitor {
public:
  virtual ~NamedVisitor() = default;
  virtual void visitCircle(Circle& c) = 0;
  virtual void visitRectangle(Rectangle& r) = 0;
};

void Circle::accept(NamedVisitor& v) { v.visitCircle(*this); }
void Rectangle::accept(NamedVisitor& v) { v.visitRectangle(*this); }

class AreaNamedVisitor : public NamedVisitor {
public:
  void visitCircle(Circle& c) override {
    std::cout << "Circle area: " << 3.14159 * c.radius() * c.radius() << '\n';
  }
  void visitRectangle(Rectangle& r) override {
    std::cout << "Rectangle area: " << r.width() * r.height() << '\n';
  }
};

int main() {
  Circle c{3.0};
  Rectangle r{4.0, 5.0};
  AreaNamedVisitor av;
  c.accept(av);
  r.accept(av);
}
```

Same dispatch, but each method name documents which visited type it handles.

## Comparison

| Aspect | Style A: `visit(Circle&)` | Style B: `visitCircle(Circle&)` |
|--------|---------------------------|----------------------------------|
| Readability | Compact | Explicit, grep-friendly |
| Overload ambiguity | Possible if many `visit(T&)` overloads coexist | Unlikely — names are unique |
| Refactoring | Renaming a shape class affects overload set | Rename one method |
| Missing handler for new shape | `visit(*this)` may bind to `visit(Shape&)` — compiles, wrong at runtime | `visitEllipse(*this)` — compile error until base adds it |
| Partial / incomplete visitor | Easy to hide gaps behind overload resolution | Pure virtual `visitXxx` forces every concrete visitor to implement or fail at compile time |

**Style A pitfall** — a helper plus many overloads can surprise you:

```cpp
class OverloadVisitor {
public:
  virtual void visit(Circle& c) = 0;
  virtual void visit(Rectangle& r) = 0;
  void visit(Shape& s) { s.accept(*this); }  // convenience helper
};
// Adding visit(Ellipse&) in a subclass, or an ambiguous using-declaration,
// can change which overload binds in subtle ways.
```

**Style A pitfall — missing overload falls back to `visit(Shape&)`:**

Add a new shape but forget to add `visit(Ellipse&)` on the visitor base:

```cpp
class Ellipse : public Shape {
public:
  void accept(OverloadVisitor& v) override {
    v.visit(*this);  // no visit(Ellipse&) — binds to visit(Shape&) instead!
  }
};

void OverloadVisitor::visit(Shape& s) { s.accept(*this); }  // helper
// Ellipse::accept → visit(Shape&) → accept → visit(Shape&) → …
```

Because `Ellipse&` converts to `Shape&`, the call **compiles** but can recurse forever or hit the wrong logic. There is no error pointing at a missing `visit(Ellipse&)`.

**Style B — same mistake is a clear compile error:**

```cpp
class Ellipse : public Shape {
public:
  void accept(Visitor& v) override {
    v.visitEllipse(*this);  // error: Visitor has no member named visitEllipse
  }
};
```

Each `accept` names exactly one method. If the visitor base lacks that `visitXxx`, the compiler fails immediately. This is the same property as Step 5's strict base: `Circle::accept` calls `visitCircle`; with pure virtual on the base, a visitor that omits it cannot be instantiated.

**Recommendation:** always prefer **Style B** (`visitCircle`, `visitRectangle`, …). Do **not** use overloaded `visit(T&)` as the primary double-dispatch API — missing pairs compile silently with Style A but fail loudly with Style B.

Both styles produce identical output when wired correctly:

```text
Circle area: 28.2743
Rectangle area: 20
```

# Step 7 — Fine-grained visitors: one operation per derived class

Instead of one fat visitor with every `visitXxx`, you can split each operation into its own small derived class. The base `Visitor` stays empty — no shared virtual API — and each derived visitor implements only the **Style B** `visitXxx` methods it needs. The visited side only knows `Visitor&` and must **`dynamic_cast`** to the specific derived visitor before calling `visitXxx`.

## Empty base + per-shape visitors

```cpp
struct Visitor {
  virtual ~Visitor() = default;
};  // no shared visitXxx API on base

struct CircleAreaVisitor : Visitor {
  void visitCircle(Circle& c) {
    std::cout << "Circle area: " << 3.14159 * c.radius() * c.radius() << '\n';
  }
};

struct RectangleAreaVisitor : Visitor {
  void visitRectangle(Rectangle& r) {
    std::cout << "Rectangle area: " << r.width() * r.height() << '\n';
  }
};
```

## Visited side: `dynamic_cast` (compile-time names, runtime choice)

Because `accept` only receives `Visitor&`, each shape hard-codes which derived visitors it supports, then calls the matching `visitXxx`:

```cpp
void Circle::accept(Visitor& v) {
  if (auto* av = dynamic_cast<CircleAreaVisitor*>(&v)) {
    av->visitCircle(*this);
  }
  // wrong visitor type? falls through — silent no-op unless you add an else branch
}

void Rectangle::accept(Visitor& v) {
  if (auto* av = dynamic_cast<RectangleAreaVisitor*>(&v)) {
    av->visitRectangle(*this);
  }
}
```

## Demonstrating match and mismatch

```cpp
int main() {
  Circle c{2.0};
  Rectangle r{3.0, 4.0};
  CircleAreaVisitor cav;

  c.accept(cav);  // prints area
  r.accept(cav);  // silent no-op — CircleAreaVisitor is wrong for Rectangle
}
```

```text
Circle area: 12.5664
```

- **Benefit:** each visitor class is tiny and implements only its `visitXxx` (Style B); no fat visitor with every pair.
- **Cost:** visited classes know visitor **subtypes** by name; `dynamic_cast` targets and `visitXxx` names are fixed at compile time. Wrong visitor → no-op or manual error handling. Less open/closed than the classic fat-visitor design.

This still involves two runtime type decisions (vtable for `accept`, RTTI for `dynamic_cast`), but the second step is deferred: the base has no virtual `visitXxx`, so dispatch goes through `dynamic_cast` + a non-virtual `visitCircle` / `visitRectangle` on the derived visitor.

# Step 8 — Propagating the visitor through a graph of visited objects

When shapes contain other shapes, or a collision pairs two operands, there are two ways to pass the visitor along.

## Strategy A — `accept` chaining (unknown static type)

Use when the next object is held as `Shape&` or `unique_ptr<Shape>` and you need double dispatch for each node. The example below adds `CompositeShape` to the hierarchy from Step 3:

```cpp
// ... Shape, Circle, Rectangle, Visitor, AreaVisitor from Step 3 ...

class CompositeShape : public Shape {
  std::vector<std::unique_ptr<Shape>> children_;

public:
  void add(std::unique_ptr<Shape> s) { children_.push_back(std::move(s)); }

  void accept(Visitor& v) override {
    for (auto& child : children_) {
      child->accept(v);  // propagate via accept — double dispatch per child
    }
  }
};

int main() {
  CompositeShape group;
  group.add(std::make_unique<Circle>(1.0));
  group.add(std::make_unique<Rectangle>(2.0, 3.0));
  AreaVisitor av;
  group.accept(av);
}
```

```text
Circle area: 3.14159
Rectangle area: 6
```

Each child calls its own `accept`, so the correct `visitXxx` runs even though the composite only stores `Shape*`.

## Strategy B — call `visitXxx` inside another `visitXxx` when the type is known

Use when you are **already inside** a `visitXxx` handler and the next shape is held as a **concrete reference** (`Rectangle&`, not `Shape&`). Call the matching `visitXxx` directly — no `other.accept(*this)` needed.

Example: detect collision between one circle and one rectangle. The visitor carries the rectangle; the circle enters via `accept`:

```cpp
// ... Shape, Circle, Rectangle, Visitor from Step 3 ...

class CircleRectangleCollisionVisitor : public Visitor {
public:
  explicit CircleRectangleCollisionVisitor(Rectangle& rect) : rect_(rect) {}

  void visitCircle(Circle& c) override {
    circle_ = &c;
    visitRectangle(rect_);  // rect_ is Rectangle& — type known, skip rect_.accept(*this)
  }

  void visitRectangle(Rectangle& r) override {
    std::cout << "Circle-Rectangle check: r=" << circle_->radius()
              << ", rect=" << r.width() << 'x' << r.height() << '\n';
  }

private:
  Rectangle& rect_;
  Circle* circle_ = nullptr;
};

int main() {
  Circle c{5.0};
  Rectangle r{4.0, 6.0};
  CircleRectangleCollisionVisitor cv{r};

  c.accept(cv);  // 1st dispatch: Circle::accept → visitCircle
                 // inside visitCircle: visitRectangle(rect_) — 2nd call, no accept on r
}
```

```text
Circle-Rectangle check: r=5, rect=4x6
```

Only the circle uses `accept` to start the chain. The rectangle's type is already known as `Rectangle&`, so `visitCircle` calls `visitRectangle(rect_)` directly instead of `rect_.accept(*this)`.

Compare with Strategy A when the partner type is **not** known at compile time:

```cpp
void visitCircle(Circle& c) override {
  circle_ = &c;
  partner_->accept(*this);  // partner_ is Shape& — must accept to dispatch
}
```

## Rule of thumb

| Situation | Use |
|-----------|-----|
| Next object stored as `Shape&` / `unique_ptr<Shape>` | `other.accept(v)` inside `visitXxx` |
| Next object already concrete (`Rectangle& r` in scope or as member) | Call `visitRectangle(r)` directly inside `visitCircle` — no second `accept` |

You can mix both in one visitor: `other.accept(*this)` when the partner is polymorphic; `visitRectangle(other)` when you already know it is a `Rectangle&`.

# Golden rules

- **`accept(Visitor&)` pure virtual on the shape base** — every concrete shape must implement it.
- Each **`accept` calls one Style B method:** `v.visitCircle(*this)`, never overloaded `v.visit(*this)` on `Shape&`.
- **`visitCircle`, `visitRectangle`, …** — named methods, not overloaded `visit(T&)`.
- **Every `visitXxx` pure virtual on `Visitor`** — same strict contract as `accept`; every concrete visitor implements all of them.
- `visitXxx` should cover all kinds of visited types, this makes life easier by enforce one to one mapping of `visitXxx` and visited types.
- Put logic in **`visitXxx` overrides** — both types are known there.
- **New operation** → new visitor class only. **New shape** → `accept` + `visitXxx` on base + every existing visitor.
- Propagate through graphs: **`other.accept(v)`** when `other` is `Shape&`; **`visitYyy(other)`** when `other` is already concrete.
- **`visitor.visit(shape)`** is optional sugar; prefer **`accept`** in APIs you define.

# References

1. [Double dispatch — Wikipedia](https://en.wikipedia.org/wiki/Double_dispatch)
2. [Double Dispatch in C++ — Vishesh Chovatiya (Medium)](https://medium.com/@visheshchovatiya/double-dispatch-in-c-7649dbdda5c9)
3. [Double Dispatch — behnamasadi/cpp_tutorials](https://github.com/behnamasadi/cpp_tutorials/blob/master/docs/double_dispatch.md)
4. [Double Dispatch / Visitor Design Pattern in Modern C++ — vishalchovatiya.com](https://vishalchovatiya.com/posts/double-dispatch-visitor-design-pattern-in-modern-cpp/)
5. [Double Dispatch with std::variant and std::visit](https://shan-weiqiang.github.io/2026/07/06/cpp-variant-visit-double-dispatch.html) — closed alternative list, `index()` + static visitor overloads (companion to this post)
