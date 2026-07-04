---
layout: post
title:  "Double Dispatch and the Visitor Pattern in C++"
date:   2026-07-04 10:00:00 +0800
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

Adding a new visited type ripples through every visitor:

```cpp
// Adding Triangle : Shape requires:
//   1. Triangle::accept       -> v.visitTriangle(*this)
//   2. Visitor::visitTriangle (pure virtual on base)
//   3. AreaVisitor::visitTriangle, PrintVisitor::visitTriangle, ...
```

Adding a new operation (new visitor) requires a new `visitXxx` in every visited class's `accept` target. This trade-off is acceptable when the class hierarchy is stable and operations vary often — compilers, ASTs, scene graphs.

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

# Step 5 — Partial visitors: only some `visitXxx`, but `accept` must match

You may implement only a subset of `visitXxx` methods, but the visited class's `accept` must only call methods that actually exist — otherwise you get a compile error (if the base keeps them pure virtual) or silent wrong behavior (if you use no-op defaults).

## Broken: missing `visitRectangle`

```cpp
class PrintCircleOnlyVisitor : public Visitor {
public:
  void visitCircle(Circle& c) override {
    std::cout << "Circle r=" << c.radius() << '\n';
  }
  // missing visitRectangle — still abstract if base has pure virtual
};

int main() {
  PrintCircleOnlyVisitor pv;  // error
}
```

```text
error: cannot declare variable 'pv' to be of abstract type 'PrintCircleOnlyVisitor'
note: because the following virtual functions are pure within 'PrintCircleOnlyVisitor':
note:   virtual void Visitor::visitRectangle(Rectangle&)
```

This is a feature: the type system prevents half-implemented visitors from being instantiated.

## Safe approach 1: default no-op in the visitor base

Make unimplemented pairs explicit no-ops instead of pure virtual:

```cpp
class PartialVisitor {
public:
  virtual ~PartialVisitor() = default;
  virtual void visitCircle(Circle& c) = 0;
  virtual void visitRectangle(Rectangle&) {}  // default no-op, not pure
};

class PrintCircleOnlyVisitor : public PartialVisitor {
public:
  void visitCircle(Circle& c) override {
    std::cout << "Circle r=" << c.radius() << '\n';
  }
  // visitRectangle inherits empty default
};
```

## Safe approach 2: never call `accept` on mismatched pairs

If you keep pure virtual `visitXxx` on the base, restrict usage at call sites:

```cpp
int main() {
  Circle c{2.0};
  PrintCircleOnlyVisitor pv;
  c.accept(pv);  // OK — visitCircle is implemented

  // Rectangle r{1.0, 1.0};
  // r.accept(pv);  // would require visitRectangle — don't pass this visitor to Rectangle
}
```

**Note:** `Rectangle::accept` always calls `v.visitRectangle(*this)`. With pure virtual `visitXxx` on the base, an incomplete visitor cannot be constructed — that is the compile-time check. No-op defaults (approach 1) are a separate, intentional choice: they let the visitor compile but do **not** catch `r.accept(circleOnlyVisitor)` at compile time. Prefer pure virtual `visitXxx` plus Style B naming so every `accept` ↔ `visitXxx` pair is explicit and missing handlers fail at compile time (see Step 6).

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

Each `accept` names exactly one method. If the visitor base lacks that `visitXxx`, the compiler fails immediately. This is the same property that makes partial visitors safe in Step 5: `Circle::accept` calls `visitCircle`; if your visitor class does not implement it (pure virtual on base), you cannot instantiate the visitor at all.

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

# Summary

1. **Problem** — virtual functions dispatch on one object; two-operand operations need double dispatch.
2. **Visited side** — every shape implements pure virtual `accept(Visitor&)`; it is always the entrance.
3. **Visitor side** — fat visitor declares `visitXxx` for every visited type; logic lives in those overrides where both types are known.
4. **Sugar** — optional `visitor.visit(shape)` forwards to `shape.accept(visitor)`; `accept` remains canonical.
5. **Partial visitors** — implement only some `visitXxx`; match with no-op defaults or restrict which shapes call `accept`.
6. **Naming** — prefer `visitCircle` over overloaded `visit(Circle&)` for clarity and safety.
7. **Fine-grained visitors** — empty visitor base, one derived class per operation, `dynamic_cast` in `accept`; flexible but couples visited classes to visitor subtypes.
8. **Propagation** — chain `other.accept(v)` when the next object is `Shape&`; inside `visitXxx`, call `visitYyy(other)` directly when `other` is already a concrete type.

**When to use it:** Visitor/double dispatch shines when a stable hierarchy of visited classes accumulates many operations (render, serialize, optimize, …). For small, closed type sets, C++17's `std::variant` + `std::visit` is often simpler and avoids the fat-visitor / fat-`accept` maintenance cost.

# References

1. [Double dispatch — Wikipedia](https://en.wikipedia.org/wiki/Double_dispatch)
2. [Double Dispatch in C++ — Vishesh Chovatiya (Medium)](https://medium.com/@visheshchovatiya/double-dispatch-in-c-7649dbdda5c9)
3. [Double Dispatch — behnamasadi/cpp_tutorials](https://github.com/behnamasadi/cpp_tutorials/blob/master/docs/double_dispatch.md)
4. [Double Dispatch / Visitor Design Pattern in Modern C++ — vishalchovatiya.com](https://vishalchovatiya.com/posts/double-dispatch-visitor-design-pattern-in-modern-cpp/)
