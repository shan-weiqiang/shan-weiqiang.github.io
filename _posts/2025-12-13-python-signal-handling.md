---
layout: post
title:  "Python singal handling"
date:   2025-12-13 9:22:46 +0800
tags: [python]
---

```python
#!/usr/bin/env python3
"""
Test to demonstrate sys.exit() behavior:

1. sys.exit() called DIRECTLY in try block:
   - Raises SystemExit exception
   - CAN be caught by except blocks
   - finally blocks execute
   - If caught, program continues
   - If NOT caught, program exits after finally

2. sys.exit() called from SIGNAL HANDLER:
   - Raises SystemExit exception
   - CAN be caught by except blocks (same as direct call!)
   - finally blocks execute
   - If caught, program continues (doesn't exit)
   - If NOT caught, program exits after finally block

CONCLUSION: sys.exit() from signal handlers behaves the SAME as direct calls
regarding exception handling. The key is whether you catch it or not.
"""

import signal
import sys
import time
import os


def test_scenario_1_no_catch():
    """Scenario 1: sys.exit() from signal handler NOT caught - program exits"""
    print("\n" + "=" * 60)
    print("Scenario 1: sys.exit() from SIGNAL HANDLER - NOT caught")
    print("=" * 60)
    print("Result: Program exits after finally block executes")
    
    cleanup_done = False
    
    def signal_handler(signum, frame):
        print(f"\n✓ Signal {signum} received!")
        print("  Calling sys.exit(0) from signal handler...")
        sys.exit(0)  # Raises SystemExit exception
    
    try:
        signal.signal(signal.SIGINT, signal_handler)
        print(f"Process PID: {os.getpid()}")
        print("Press Ctrl+C to trigger sys.exit(0) from signal handler")
        print("Waiting 5 seconds...")
        time.sleep(5)
        print("Normal completion (should not reach here if signal sent)")
    finally:
        cleanup_done = True
        print("\n✓ FINALLY BLOCK EXECUTED!")
        print(f"cleanup_done = {cleanup_done}")
        print("(Program will exit after finally block)")
        print("(No except block to catch SystemExit)")
    
    print("This will NOT be executed (program exits after finally)!")


def test_scenario_2_catch_inside_try():
    """Scenario 2: Catch SystemExit from signal handler INSIDE try block"""
    print("\n" + "=" * 60)
    print("Scenario 2: sys.exit() from SIGNAL HANDLER - catch INSIDE try")
    print("=" * 60)
    print("✓ This WILL catch the exception!")
    print("Result: Exception caught, program continues, finally executes")
    
    cleanup_done = False
    
    def signal_handler(signum, frame):
        print(f"\n✓ Signal {signum} received!")
        print("  Calling sys.exit(0) from signal handler...")
        sys.exit(0)  # Raises SystemExit exception
    
    try:
        signal.signal(signal.SIGINT, signal_handler)
        print(f"Process PID: {os.getpid()}")
        print("Press Ctrl+C to trigger sys.exit(0) from signal handler")
        print("Waiting 5 seconds...")
        time.sleep(5)
        print("Normal completion")
    except SystemExit as e:
        print(f"\n✓ SystemExit CAUGHT inside try block!")
        print(f"  Exit code: {e.code}")
        print("  Program continues (doesn't exit)")
        print("  ✓ This proves sys.exit() from signal handler CAN be caught!")
    finally:
        cleanup_done = True
        print("\n✓ FINALLY BLOCK EXECUTED!")
        print(f"cleanup_done = {cleanup_done}")
        print("(Finally executes, then program continues)")

    print("✓ This WILL be executed (exception was caught, program continues)!")



def test_scenario_3_catch_outside_try():
    """Scenario 3: Catch SystemExit from signal handler OUTSIDE try-finally"""
    print("\n" + "=" * 60)
    print("Scenario 3: sys.exit() from SIGNAL HANDLER - catch OUTSIDE try-finally")
    print("=" * 60)
    print("✓ This WILL catch the exception!")
    print("Result: Exception caught after finally, program continues")
    
    cleanup_done = False
    
    def signal_handler(signum, frame):
        print(f"\n✓ Signal {signum} received!")
        print("  Calling sys.exit(0) from signal handler...")
        sys.exit(0)  # Raises SystemExit exception
    
    try:
        try:
            signal.signal(signal.SIGINT, signal_handler)
            print(f"Process PID: {os.getpid()}")
            print("Press Ctrl+C to trigger sys.exit(0) from signal handler")
            print("Waiting 5 seconds...")
            time.sleep(5)
            print("Normal completion")
        finally:
            cleanup_done = True
            print("\n✓ FINALLY BLOCK EXECUTED!")
            print(f"cleanup_done = {cleanup_done}")
            print("(Finally executes before exception propagates)")
    except SystemExit as e:
        print(f"\n✓ SystemExit CAUGHT outside try-finally block!")
        print(f"  Exit code: {e.code}")
        print("  Program continues (doesn't exit)")
        print("  ✓ This proves sys.exit() from signal handler CAN be caught!")
        print("  Note: Finally executed BEFORE this catch")
    
    print("✓ This WILL be executed (exception was caught, program continues)!")


def test_comparison_side_by_side():
    """Side-by-side comparison: signal handler vs direct call"""
    print("\n" + "=" * 60)
    print("SIDE-BY-SIDE COMPARISON")
    print("=" * 60)
    print("\nTest A: sys.exit() from SIGNAL HANDLER (with catch)")
    print("-" * 60)
    
    cleanup_a = False
    caught_a = False
    
    def signal_handler(signum, frame):
        print("  Signal handler: calling sys.exit(0)...")
        sys.exit(0)
    
    try:
        signal.signal(signal.SIGINT, signal_handler)
        print(f"  Process PID: {os.getpid()}")
        print("  Press Ctrl+C to test...")
        print("  Waiting 3 seconds...")
        time.sleep(3)
    except SystemExit:
        caught_a = True
        print("  ✓ SystemExit CAUGHT")
    finally:
        cleanup_a = True
        print("  ✓ Finally executed")
    
    print(f"\n  Result: caught={caught_a}, finally={cleanup_a}")
    print("  ✓ If signal was sent: caught=True, program continues")
    
    print("\nTest B: sys.exit() called DIRECTLY (with catch)")
    print("-" * 60)
    
    cleanup_b = False
    caught_b = False
    
    try:
        print("  Calling sys.exit(0) directly...")
        sys.exit(0)
    except SystemExit:
        caught_b = True
        print("  ✓ SystemExit CAUGHT")
    finally:
        cleanup_b = True
        print("  ✓ Finally executed")
    
    print(f"\n  Result: caught={caught_b}, finally={cleanup_b}")
    print("  ✓ Exception was caught, program continues")
    
    print("\n" + "=" * 60)
    print("CONCLUSION:")
    print("=" * 60)
    print("Signal handler: SystemExit CAN be caught (same as direct call)")
    print("Direct call:     SystemExit CAN be caught")
    print("Both cases:      finally blocks execute")
    print("Key point:       If caught, program continues; if not, exits")
    print("=" * 60)


def test_scenario_4_direct_sys_exit():
    """Scenario 4: Direct sys.exit() call (NOT from signal handler)"""
    print("\n" + "=" * 60)
    print("Scenario 4: Direct sys.exit() call (NOT from signal)")
    print("=" * 60)
    print("✓ This WILL be caught by except block!")
    print("Result: Exception caught, program continues, finally executes")
    
    cleanup_done = False
    
    try:
        print("Calling sys.exit(0) directly in try block...")
        sys.exit(0)  # Raises SystemExit in normal execution context
        print("This line should not be reached")
    # ✅ This except block WILL catch SystemExit when called directly!
    except SystemExit as e:
        print(f"✓ SystemExit CAUGHT: exit code = {e.code}")
        print("  Program continues (doesn't exit)")
        print("  This works because sys.exit() was called directly,")
        print("  not from a signal handler!")
    finally:
        cleanup_done = True
        print("✓ FINALLY BLOCK EXECUTED!")
        print(f"cleanup_done = {cleanup_done}")


def main():
    print("=" * 60)
    print("sys.exit() and SystemExit Exception Handling Test")
    print("=" * 60)
    print("\nKEY FINDINGS:")
    print("=" * 60)
    print("1. sys.exit() called DIRECTLY in try block:")
    print("   ✓ Raises SystemExit exception")
    print("   ✓ CAN be caught by except blocks")
    print("   ✓ If caught, program continues")
    print("   ✓ If NOT caught, program exits after finally")
    print("   ✓ finally blocks ALWAYS execute")
    print()
    print("2. sys.exit() called from SIGNAL HANDLER:")
    print("   ✓ Raises SystemExit exception")
    print("   ✓ CAN be caught by except blocks (same as direct call!)")
    print("   ✓ If caught, program continues (doesn't exit)")
    print("   ✓ If NOT caught, program exits after finally block")
    print("   ✓ finally blocks ALWAYS execute")
    print()
    print("CONCLUSION: sys.exit() from signal handlers behaves the SAME")
    print("            as direct calls regarding exception handling.")
    print("            The key is whether you catch it or not.")
    print("=" * 60)
    
    print("\n" + "-" * 60)
    print("Choose a test scenario:")
    print("1. sys.exit() from signal handler - NOT caught (exits)")
    print("2. Catch INSIDE try (signal handler) - WILL catch (continues)")
    print("3. Catch OUTSIDE try-finally (signal handler) - WILL catch (continues)")
    print("4. Direct sys.exit() call - WILL be caught (continues)")
    print("5. Side-by-side comparison")
    print("-" * 60)
    
    choice = input("\nEnter choice (1-5) or press Enter to run comparison: ").strip()
    
    if choice == "1":
        test_scenario_1_no_catch()
    elif choice == "2":
        test_scenario_2_catch_inside_try()
    elif choice == "3":
        test_scenario_3_catch_outside_try()
    elif choice == "4":
        test_scenario_4_direct_sys_exit()
    elif choice == "5":
        test_comparison_side_by_side()
    else:
        # Run all tests
        print("\nRunning all scenarios...")
        print("\n⚠️  Note: Scenarios 1-3 require manual signal sending")
        print("⚠️  You can skip by waiting for timeout or pressing Enter\n")
        
        try:
            test_scenario_4_direct_sys_exit()
        except SystemExit:
            pass
        
        print("\n" + "=" * 60)
        print("SUMMARY - KEY FINDINGS")
        print("=" * 60)
        print("1. sys.exit() called DIRECTLY:")
        print("   ✓ Raises SystemExit exception")
        print("   ✓ CAN be caught by except blocks")
        print("   ✓ If caught, program continues")
        print("   ✓ If NOT caught, program exits after finally")
        print("   ✓ finally blocks ALWAYS execute")
        print()
        print("2. sys.exit() called from SIGNAL HANDLER:")
        print("   ✓ Raises SystemExit exception")
        print("   ✓ CAN be caught by except blocks (same as direct call!)")
        print("   ✓ If caught, program continues (doesn't exit)")
        print("   ✓ If NOT caught, program exits after finally block")
        print("   ✓ finally blocks ALWAYS execute")
        print()
        print("CONCLUSION:")
        print("sys.exit() from signal handlers behaves the SAME as direct")
        print("calls regarding exception handling. Both can be caught,")
        print("and if caught, the program continues. If not caught, the")
        print("program exits after the finally block executes.")
        print("=" * 60)


if __name__ == "__main__":
    main()


```
