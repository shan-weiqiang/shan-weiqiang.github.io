class Parent:
    def p_method(self):
        print("Parent method, self is:", self)

class Child(Parent):
    def c_method(self):
        print("Child method, self is:", self)

c = Child()
c.p_method()  # Works — no casting needed