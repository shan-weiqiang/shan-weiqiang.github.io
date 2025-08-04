---
layout: post
title:  "Type systems: Part III Json"
date:   2025-08-01 9:22:46 +0800
tags: [programming]
---

Previously:
- [Type systems: Part I](https://shan-weiqiang.github.io/2024/07/14/understanding-types.html)
- [Type systems: Part II Protobuf Reflection](https://shan-weiqiang.github.io/2025/06/14/protobuf-reflection.html)

Now:
- json itself is a kind of *data format*, NOT type system. To operate on json, we need a *type system*, which is the program to operate json data. This program might be a dynamic typing system, like `nolmann::json` or static typing system, for example a program that can only parse data that are of specific json format.
- *json schema* can be loosely compared with *type*, since a *json schema* actually defines a *class* of json data format, like what the *type* does
- Since user directly write *json data*, which means that the format is *inherently* dynamic, so json inherently needs a dynamic type system to represent *json data*. Of course, static type system can also be used, but this requires that the user write the *json data* with fixed format, otherwise, the parse will fail.
- `nlohmann::json` is a *dynamic type* system to represent json. It's *dynamic* in the sense of that it can represent any json, but itself is *static*. All programs are *static* in the low level, *dynamic* only are acheived through static programs. 

This is a json file. It's a *data format*, meaning that this is a piece of *data*. It is unique and can not have any other *instantiation*.
```json
{
    "MyMessage": [
        {
            "name": "weiqiang.shan"
        },
        {
            "age": 18
        },
        23,
        "Hello"
    ]
}
```
This is a *json schema*. It describes one kind of  *json data*. This schema can have many json data *instantiations*, like above json file. It works like a *type*. But it is not actually a *type*, since there is no type name. It is just a descriptor of what should a json data look like, what attributes json data should have, etc. It does not define a *generalized* type that can be *reused* with a type name. 
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "MyMessage": {
      "type": "array",
      "minItems": 4,
      "maxItems": 4,
      "items": [
        {
          "type": "object",
          "properties": {
            "name": {
              "type": "string"
            }
          },
          "required": ["name"],
          "additionalProperties": false
        },
        {
          "type": "object",
          "properties": {
            "age": {
              "type": "number"
            }
          },
          "required": ["age"],
          "additionalProperties": false
        },
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    }
  },
  "required": ["MyMessage"],
  "additionalProperties": false
} 
```
This is a *mirror* protobuf definition for above json schema. It can be used to represent above json data. If we use this protobuf definiton to write a program, we build a *static type system* for above json schema, which can only parse this kinds of json data. Unlike json schema, every type has a *name*, which can be used to *instantiate* type instance and can be *reused*.
```
syntax = "proto3";

package tmp;

// Message representing the root object
message RootMessage {
  repeated MyMessageItem MyMessage = 1;
}

// Union type to represent the mixed array items
message MyMessageItem {
  oneof value {
    NameObject name_value = 1;
    AgeObject age_value = 2;
    int32 number_value = 3;
    string string_value = 4;
  }
}

// Object with name property
message NameObject {
  string name = 1;
}

// Object with age property  
message AgeObject {
  int32 age = 1;
} 
```
This how the `nlohmann::json` dynamically represents all json data. At it's core, it actually is a *type erasure* system. All json data, whether it's numbers, strings, binary, object , list are type erased and be represent using one single type. Type erasure happens during construction, *when the binding of constructor and destructor is finished*, through `value_t`, which is enum to represent type of json data. Different `value_t` will be created and destructed differently. This is the core idea of *type erasure*: **hide specific type information in implementation, while in the interface expose unified type representation and complete the binding during construction.**.

- [Type Erasure: Part I](https://shan-weiqiang.github.io/2025/04/20/type-erasure.html)
- [Type Erasure Part Two: How std::function Works](https://shan-weiqiang.github.io/2025/06/29/type-erasure-part-two.html)
- [Type Erasure Part Three: The Downside](https://shan-weiqiang.github.io/2025/07/08/type-erasure-part-three.html)
  
```c++
    /*!
    @brief a JSON value

    The actual storage for a JSON value of the @ref basic_json class. This
    union combines the different storage types for the JSON value types
    defined in @ref value_t.

    JSON type | value_t type    | used type
    --------- | --------------- | ------------------------
    object    | object          | pointer to @ref object_t
    array     | array           | pointer to @ref array_t
    string    | string          | pointer to @ref string_t
    boolean   | boolean         | @ref boolean_t
    number    | number_integer  | @ref number_integer_t
    number    | number_unsigned | @ref number_unsigned_t
    number    | number_float    | @ref number_float_t
    binary    | binary          | pointer to @ref binary_t
    null      | null            | *no value is stored*

    @note Variable-length types (objects, arrays, and strings) are stored as
    pointers. The size of the union should not exceed 64 bits if the default
    value types are used.

    @since version 1.0.0
    */
    union json_value
    {
        /// object (stored with pointer to save storage)
        object_t* object;
        /// array (stored with pointer to save storage)
        array_t* array;
        /// string (stored with pointer to save storage)
        string_t* string;
        /// binary (stored with pointer to save storage)
        binary_t* binary;
        /// boolean
        boolean_t boolean;
        /// number (integer)
        number_integer_t number_integer;
        /// number (unsigned integer)
        number_unsigned_t number_unsigned;
        /// number (floating-point)
        number_float_t number_float;

        /// default constructor (for null values)
        json_value() = default;
        /// constructor for booleans
        json_value(boolean_t v) noexcept : boolean(v) {}
        /// constructor for numbers (integer)
        json_value(number_integer_t v) noexcept : number_integer(v) {}
        /// constructor for numbers (unsigned)
        json_value(number_unsigned_t v) noexcept : number_unsigned(v) {}
        /// constructor for numbers (floating-point)
        json_value(number_float_t v) noexcept : number_float(v) {}
        /// constructor for empty values of a given type
        json_value(value_t t)
        {
            switch (t)
            {
                case value_t::object:
                {
                    object = create<object_t>();
                    break;
                }

                case value_t::array:
                {
                    array = create<array_t>();
                    break;
                }

                case value_t::string:
                {
                    string = create<string_t>("");
                    break;
                }

                case value_t::binary:
                {
                    binary = create<binary_t>();
                    break;
                }

                case value_t::boolean:
                {
                    boolean = static_cast<boolean_t>(false);
                    break;
                }

                case value_t::number_integer:
                {
                    number_integer = static_cast<number_integer_t>(0);
                    break;
                }

                case value_t::number_unsigned:
                {
                    number_unsigned = static_cast<number_unsigned_t>(0);
                    break;
                }

                case value_t::number_float:
                {
                    number_float = static_cast<number_float_t>(0.0);
                    break;
                }

                case value_t::null:
                {
                    object = nullptr;  // silence warning, see #821
                    break;
                }

                case value_t::discarded:
                default:
                {
                    object = nullptr;  // silence warning, see #821
                    if (JSON_HEDLEY_UNLIKELY(t == value_t::null))
                    {
                        JSON_THROW(other_error::create(500, "961c151d2e87f2686a955a9be24d316f1362bf21 3.11.3", nullptr)); // LCOV_EXCL_LINE
                    }
                    break;
                }
            }
        }

        /// constructor for strings
        json_value(const string_t& value) : string(create<string_t>(value)) {}

        /// constructor for rvalue strings
        json_value(string_t&& value) : string(create<string_t>(std::move(value))) {}

        /// constructor for objects
        json_value(const object_t& value) : object(create<object_t>(value)) {}

        /// constructor for rvalue objects
        json_value(object_t&& value) : object(create<object_t>(std::move(value))) {}

        /// constructor for arrays
        json_value(const array_t& value) : array(create<array_t>(value)) {}

        /// constructor for rvalue arrays
        json_value(array_t&& value) : array(create<array_t>(std::move(value))) {}

        /// constructor for binary arrays
        json_value(const typename binary_t::container_type& value) : binary(create<binary_t>(value)) {}

        /// constructor for rvalue binary arrays
        json_value(typename binary_t::container_type&& value) : binary(create<binary_t>(std::move(value))) {}

        /// constructor for binary arrays (internal type)
        json_value(const binary_t& value) : binary(create<binary_t>(value)) {}

        /// constructor for rvalue binary arrays (internal type)
        json_value(binary_t&& value) : binary(create<binary_t>(std::move(value))) {}

        void destroy(value_t t)
        {
            if (
                (t == value_t::object && object == nullptr) ||
                (t == value_t::array && array == nullptr) ||
                (t == value_t::string && string == nullptr) ||
                (t == value_t::binary && binary == nullptr)
            )
            {
                //not initialized (e.g. due to exception in the ctor)
                return;
            }
            if (t == value_t::array || t == value_t::object)
            {
                // flatten the current json_value to a heap-allocated stack
                std::vector<basic_json> stack;

                // move the top-level items to stack
                if (t == value_t::array)
                {
                    stack.reserve(array->size());
                    std::move(array->begin(), array->end(), std::back_inserter(stack));
                }
                else
                {
                    stack.reserve(object->size());
                    for (auto&& it : *object)
                    {
                        stack.push_back(std::move(it.second));
                    }
                }

                while (!stack.empty())
                {
                    // move the last item to local variable to be processed
                    basic_json current_item(std::move(stack.back()));
                    stack.pop_back();

                    // if current_item is array/object, move
                    // its children to the stack to be processed later
                    if (current_item.is_array())
                    {
                        std::move(current_item.m_data.m_value.array->begin(), current_item.m_data.m_value.array->end(), std::back_inserter(stack));

                        current_item.m_data.m_value.array->clear();
                    }
                    else if (current_item.is_object())
                    {
                        for (auto&& it : *current_item.m_data.m_value.object)
                        {
                            stack.push_back(std::move(it.second));
                        }

                        current_item.m_data.m_value.object->clear();
                    }

                    // it's now safe that current_item get destructed
                    // since it doesn't have any children
                }
            }

            switch (t)
            {
                case value_t::object:
                {
                    AllocatorType<object_t> alloc;
                    std::allocator_traits<decltype(alloc)>::destroy(alloc, object);
                    std::allocator_traits<decltype(alloc)>::deallocate(alloc, object, 1);
                    break;
                }

                case value_t::array:
                {
                    AllocatorType<array_t> alloc;
                    std::allocator_traits<decltype(alloc)>::destroy(alloc, array);
                    std::allocator_traits<decltype(alloc)>::deallocate(alloc, array, 1);
                    break;
                }

                case value_t::string:
                {
                    AllocatorType<string_t> alloc;
                    std::allocator_traits<decltype(alloc)>::destroy(alloc, string);
                    std::allocator_traits<decltype(alloc)>::deallocate(alloc, string, 1);
                    break;
                }

                case value_t::binary:
                {
                    AllocatorType<binary_t> alloc;
                    std::allocator_traits<decltype(alloc)>::destroy(alloc, binary);
                    std::allocator_traits<decltype(alloc)>::deallocate(alloc, binary, 1);
                    break;
                }

                case value_t::null:
                case value_t::boolean:
                case value_t::number_integer:
                case value_t::number_unsigned:
                case value_t::number_float:
                case value_t::discarded:
                default:
                {
                    break;
                }
            }
        }
    };
```


