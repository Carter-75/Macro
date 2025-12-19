import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

MIN_SUPPORTED_PYTHON = (3, 8)
MAX_TESTED_MINOR = 13

if sys.version_info < MIN_SUPPORTED_PYTHON:
    raise SystemExit(
        f"Python {MIN_SUPPORTED_PYTHON[0]}.{MIN_SUPPORTED_PYTHON[1]} or newer is required; "
        f"detected {sys.version.split()[0]}"
    )

if sys.version_info.major == 3 and sys.version_info.minor > MAX_TESTED_MINOR:
    print(
        f"[INFO] Running on Python {sys.version.split()[0]}. "
        "This version has not been formally tested, but the script should still work as long as "
        "the 'pynput' dependency installs successfully."
    )

try:
    from pynput import mouse, keyboard
    from pynput.mouse import Controller as MouseController
except ImportError as exc:  # pragma: no cover - env specific
    raise SystemExit(
        "Missing optional dependency 'pynput'. Install it with 'python -m pip install -r requirements.txt' "
        "or 'python -m pip install pynput'."
    ) from exc

class MouseMover:
    def __init__(self, interval_mins: float, duration_mins: Optional[float] = None):
        self.interval_mins = interval_mins
        self.duration_mins = duration_mins
        self.pattern_file = "mouse_pattern.json"
        self.mouse_positions: List[Dict[str, Any]] = []
        self.recording = False
        self.running = True
        self.mouse_controller = MouseController()
        self.user_moved_mouse = False
        self.currently_replaying = False
        self.grace_period_start: Optional[float] = None
        self.grace_period_active = False
        self.grace_period_duration = 0.5
        
    def record_mouse_movement(self, duration: int = 5):
        """Record mouse movements and clicks for specified duration"""
        print(f"\nRecording mouse movement and clicks for {duration} seconds...")
        
        print("Recording starts in:")
        for i in range(3, 0, -1):
            print(f"{i}...")
            time.sleep(1)
        print("GO! Move your mouse and click around to create a pattern!")
        
        self.mouse_positions = []
        self.recording = True
        start_time = time.time()
        
        def on_move(x: int, y: int):
            if self.recording:
                elapsed = time.time() - start_time
                self.mouse_positions.append({
                    'type': 'move',
                    'x': x,
                    'y': y,
                    'timestamp': elapsed
                })

        def on_click(x: int, y: int, button: mouse.Button, pressed: bool):
            if self.recording:
                elapsed = time.time() - start_time
                self.mouse_positions.append({
                    'type': 'click',
                    'x': x,
                    'y': y,
                    'button': str(button),
                    'pressed': pressed,
                    'timestamp': elapsed
                })
        
        # Set up mouse listener
        listener = mouse.Listener(on_move=on_move, on_click=on_click)
        listener.start()
        
        # Record for specified duration
        time.sleep(duration)
        self.recording = False
        listener.stop()
        
        print(f"Recording complete! Captured {len(self.mouse_positions)} events.")
        
    def save_pattern(self):
        """Save recorded pattern to file"""
        with open(self.pattern_file, 'w') as f:
            json.dump(self.mouse_positions, f)
        print(f"Pattern saved to {self.pattern_file}")
        
    def load_pattern(self):
        """Load pattern from file"""
        try:
            with open(self.pattern_file, 'r') as f:
                self.mouse_positions = json.load(f)
            print(f"Loaded pattern with {len(self.mouse_positions)} positions.")
            return True
        except FileNotFoundError:
            print("No saved pattern found.")
            return False
            
    def replay_pattern(self):
        """Replay the recorded mouse pattern with natural human-like sampling"""
        if not self.mouse_positions:
            print("No pattern to replay!")
            return
        
        print("Replaying mouse pattern with human-like imperfections...")
        self.currently_replaying = True
        self.user_moved_mouse = False
        
        # Use approximately 85% of points from the pattern
        selected_points: List[Dict[str, Any]] = []
        total_points = len(self.mouse_positions)
        
        for i, pos in enumerate(self.mouse_positions):
            # 85% chance to include each point, plus always include first and last
            # Always include clicks to ensure actions are performed
            is_click = pos.get('type') == 'click'
            if is_click or i == 0 or i == total_points - 1 or random.random() < 0.85:
                selected_points.append(pos)
        
        print(f"Selected {len(selected_points)} points from {total_points} (~{len(selected_points)/total_points*100:.1f}%)")
        
        # Now move through the selected points with exact positions (0 jitter)
        prev_timestamp = 0.0
        
        for pos in selected_points:
            if not self.running or self.user_moved_mouse:
                if self.user_moved_mouse:
                    print("\n⚠️  User mouse movement detected! Stopping replay and resetting interval...")
                break
            
            # No random shifts - use exact recorded positions for 0 jitter
            target_x = int(pos['x'])
            target_y = int(pos['y'])
            
            # Ensure position stays within reasonable bounds
            target_x = max(0, min(target_x, 3840))
            target_y = max(0, min(target_y, 2160))
            
            # Calculate time to reach this point (with randomness 85-115%)
            current_timestamp = pos['timestamp']
            time_to_move = current_timestamp - prev_timestamp
            
            if time_to_move > 0:
                # Add a little randomness to timing (85% to 115%)
                time_variation = random.uniform(0.85, 1.15)
                time_to_move *= time_variation
                
                # Smooth movement to this target point
                current_x, current_y = self.mouse_controller.position
                
                # Calculate distance to determine number of steps
                distance = ((target_x - current_x) ** 2 + (target_y - current_y) ** 2) ** 0.5
                steps = max(5, int(distance / 30))  # More steps for longer distances
                
                # Time per step to match original speed
                base_sleep_per_step = time_to_move / steps if steps > 0 else 0.001
                
                for step in range(steps):
                    if not self.running or self.user_moved_mouse:
                        if self.user_moved_mouse:
                            print("\n⚠️  User mouse movement detected! Stopping replay and resetting interval...")
                        break
                    
                    # Use ease-in-out curve instead of linear for more human-like movement
                    progress = (step + 1) / steps
                    # Ease-in-out formula: smoother acceleration/deceleration
                    eased_progress = progress * progress * (3.0 - 2.0 * progress)
                    
                    # Calculate position with easing
                    expected_x = int(current_x + (target_x - current_x) * eased_progress)
                    expected_y = int(current_y + (target_y - current_y) * eased_progress)
                    
                    # Add subtle hand tremor (±2 pixels) to simulate human imperfection
                    tremor_x = random.randint(-2, 2)
                    tremor_y = random.randint(-2, 2)
                    actual_x = expected_x + tremor_x
                    actual_y = expected_y + tremor_y
                    
                    # Move mouse with tremor
                    self.mouse_controller.position = (actual_x, actual_y)
                    
                    # Variable timing - add small random variation to each step (±20%)
                    sleep_variation = random.uniform(0.8, 1.2)
                    varied_sleep = base_sleep_per_step * sleep_variation
                    time.sleep(varied_sleep)
                    
                    # Check if grace period has expired
                    if self.grace_period_active and self.grace_period_start is not None:
                        if time.time() - self.grace_period_start > self.grace_period_duration:
                            self.grace_period_active = False
                            print("(Grace period ended - user detection now active)")
                    
                    # Check if user moved the mouse (only if grace period is over)
                    # Need to account for our own tremor (±2) plus some tolerance
                    if not self.grace_period_active:
                        current_actual_x, current_actual_y = self.mouse_controller.position
                        # Check if moved more than tremor + tolerance (20 pixels total)
                        if abs(current_actual_x - actual_x) > 20 or abs(current_actual_y - actual_y) > 20:
                            self.user_moved_mouse = True
                            break
            else:
                # If no time difference, just move there instantly
                self.mouse_controller.position = (target_x, target_y)
            
            # Handle clicks
            if pos.get('type') == 'click':
                button_str = pos['button']
                button = mouse.Button.left
                if 'right' in button_str:
                    button = mouse.Button.right
                elif 'middle' in button_str:
                    button = mouse.Button.middle
                elif 'x1' in button_str:
                    button = mouse.Button.x1
                elif 'x2' in button_str:
                    button = mouse.Button.x2
                
                if pos['pressed']:
                    self.mouse_controller.press(button)
                else:
                    self.mouse_controller.release(button)

            prev_timestamp = current_timestamp
            
            # Random micro-pauses between points for human-like behavior
            # Occasional longer pauses (15% chance)
            if random.random() < 0.15 and not self.user_moved_mouse:
                time.sleep(random.uniform(0.02, 0.15))
            # Very brief micro-pauses (30% chance) - simulates human hesitation
            elif random.random() < 0.3 and not self.user_moved_mouse:
                time.sleep(random.uniform(0.005, 0.025))
        
        self.currently_replaying = False
        if not self.user_moved_mouse:
            print("Pattern replay complete!")
        
    def setup_keyboard_listener(self):
        """Set up F10 key listener to stop the script"""
        def on_press(key: Any):
            try:
                if key == keyboard.Key.f10:
                    print("\n\nF10 pressed! Stopping script...")
                    self.running = False
                    return False  # Stop listener
            except AttributeError:
                pass
            return None
        
        listener = keyboard.Listener(on_press=on_press) # type: ignore
        listener.start()
        return listener
        
    def run(self):
        """Main execution loop"""
        print("=" * 50)
        print("MOUSE MOVER SCRIPT (ANTI-DETECTION MODE)")
        print("=" * 50)
        
        # Check if pattern exists
        pattern_exists = os.path.exists(self.pattern_file)
        
        if pattern_exists:
            choice = input("Saved pattern found. Use it? (y/n) or 'r' to reset: ").lower()
            if choice == 'r':
                print("Resetting pattern...")
                self.record_mouse_movement(5)
                self.save_pattern()
                self.grace_period_duration = 5.0
            elif choice == 'y':
                self.load_pattern()
                self.grace_period_duration = 0.5
            else:
                self.record_mouse_movement(5)
                self.save_pattern()
                self.grace_period_duration = 5.0
        else:
            print("No saved pattern found. Recording new pattern...")
            self.record_mouse_movement(5)
            self.save_pattern()
            self.grace_period_duration = 5.0
        
        if not self.mouse_positions:
            print("No pattern available. Exiting.")
            return

        # Initial 3 second countdown
        print("\nStarting in 3 seconds...")
        for i in range(3, 0, -1):
            print(f"{i}...")
            time.sleep(1)
        print("Starting!\n")
        
        # Set up F10 listener
        self.setup_keyboard_listener()
        
        # Calculate end time if duration is specified
        end_time = None
        if self.duration_mins:
            end_time = datetime.now() + timedelta(minutes=self.duration_mins)
            print(f"\nRunning for {self.duration_mins} minutes (until {end_time.strftime('%H:%M:%S')})")
        else:
            print("\nRunning indefinitely (press F10 to stop)")
        
        print(f"Moving mouse every {self.interval_mins} minute(s)")
        print("Press F10 at any time to stop!")
        print("Move your mouse during replay to take control and reset the timer!\n")
        
        # Start grace period at the very beginning
        self.grace_period_start = time.time()
        self.grace_period_active = True
        print(f"({self.grace_period_duration}-second grace period active - user detection will start after)\n")
        
        iteration = 0
        # Main loop
        while self.running:
            iteration += 1
            current_time = datetime.now()
            
            # Check if we've reached the end time
            if end_time and current_time >= end_time:
                print("\nDuration limit reached. Stopping...")
                break
            
            print(f"\n[{current_time.strftime('%H:%M:%S')}] Iteration #{iteration}")
            self.replay_pattern()
            
            if not self.running:
                break
            
            # If user moved mouse during replay, reset immediately and restart grace period
            if self.user_moved_mouse:
                print("Interval timer reset! Waiting full interval before next replay...")
                self.user_moved_mouse = False  # Reset flag for next iteration
                # Restart grace period after user takes control
                self.grace_period_start = time.time()
                self.grace_period_active = True
                print(f"({self.grace_period_duration}-second grace period restarted after manual control)\n")
            
            # Wait for the interval with subtle random variation (±10-20% of interval)
            random_variation = random.uniform(0.85, 1.15)  # 85% to 115% of original interval
            actual_wait_mins = self.interval_mins * random_variation
            wait_seconds = actual_wait_mins * 60
            
            print(f"Waiting ~{actual_wait_mins:.1f} minute(s) until next movement...")
            
            # Break waiting into 1-second chunks to check for F10
            for _ in range(int(wait_seconds)):
                if not self.running:
                    break
                time.sleep(1)
        
        print("\n" + "=" * 50)
        print("Script stopped!")
        print("=" * 50)

def main():
    parser = argparse.ArgumentParser(
        description="Automated mouse mover - records and replays mouse patterns (movements and clicks) with human-like imperfections to avoid detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Move mouse every ~5 minutes (slightly randomized), run indefinitely
  python mouse_mover.py -i 5
  
  # Move mouse every ~2 minutes (slightly randomized) for 60 minutes total
  python mouse_mover.py -i 2 -d 60
  
  # Move mouse every ~10 minutes (slightly randomized) for 120 minutes
  python mouse_mover.py -i 10 -d 120

REPLAY FEATURES:
  - Pattern sampling: Uses ~85% of recorded points (randomly skips ~15%), but always includes clicks
  - Human-like movement: Ease-in-out curves (not linear)
  - Hand tremor simulation: ±2 pixel micro-movements during motion
  - Variable timing: Each step varies ±20% from base speed
  - Timing preservation: Matches your original movement speed (85-115% variation)
  - Interval variations: 85% to 115% of specified interval
  - Random micro-pauses: 15% chance longer (0.02-0.15s), 30% chance brief (0.005-0.025s)

ANTI-DETECTION FEATURES:
  - Non-linear curves (ease-in-out) mimic natural acceleration/deceleration
  - Subtle hand tremor prevents perfect pixel-aligned movements
  - Variable step timing prevents robotic consistency
  - Random point sampling ensures no two replays are identical
  - Micro-pauses simulate human hesitation and decision-making

MANUAL CONTROL:
  - Move your mouse during replay to instantly take control
  - 0.5-second grace period at start and after you take control
  - Script detects movement >15 pixels after grace period ends
  - Interval timer resets and grace period restarts when you take control
  
Press F10 at any time to stop the script completely!
        """
    )
    
    parser.add_argument(
        '-i', '--interval',
        type=float,
        required=True,
        help='Time interval in minutes between mouse movements'
    )
    
    parser.add_argument(
        '-d', '--duration',
        type=float,
        default=None,
        help='Total duration in minutes (omit for unlimited)'
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.interval <= 0:
        print("Error: Interval must be greater than 0")
        return
    
    if args.duration is not None and args.duration <= 0:
        print("Error: Duration must be greater than 0")
        return
    
    # Create and run the mouse mover
    mover = MouseMover(args.interval, args.duration)
    
    try:
        mover.run()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user (Ctrl+C)")
    except Exception as e:
        print(f"\nError occurred: {e}")

if __name__ == "__main__":
    main()
