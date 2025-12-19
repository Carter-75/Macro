import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import ctypes
import threading

try:
    import winsound
except ImportError:  # pragma: no cover - non-Windows
    winsound = None

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
    def __init__(
        self,
        interval_mins: float,
        duration_mins: Optional[float] = None,
        alarm_interval_mins: float = 0.0
    ):
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
        self.activity_window_seconds = 5.0
        self.activity_postpone_seconds = 5.0
        self.activity_movement_threshold = 12
        self.activity_poll_interval = 0.1
        self.is_windows = sys.platform.startswith('win')
        self._vk_codes = {
            'left': 0x01,
            'right': 0x02,
            'middle': 0x04,
            'x1': 0x05,
            'x2': 0x06,
        }
        self.alarm_interval_mins = max(0.0, alarm_interval_mins or 0.0)
        self._alarm_stop_event = threading.Event()
        self.alarm_thread: Optional[threading.Thread] = None
        if self.alarm_interval_mins > 0:
            self._start_alarm_thread()
        
    def record_mouse_movement(self, duration: int = 5):
        """Record mouse movements and clicks for specified duration

        Attempts to use the `pynput` listener first; if the listener fails
        or records no events (some Windows/Python combinations cause listener
        issues), fall back to a polling-based recorder that uses the Windows
        `GetAsyncKeyState` API via `ctypes` when available.
        """
        print(f"\nRecording mouse movement and clicks for {duration} seconds...")

        print("Recording starts in:")
        for i in range(3, 0, -1):
            print(f"{i}...")
            self._sleep_with_cancel(1.0, step=1.0)
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

        # Try to use pynput listener first (may raise or capture nothing)
        try:
            listener = mouse.Listener(on_move=on_move, on_click=on_click)
            listener.start()

            # Record for specified duration
            self._sleep_with_cancel(duration, step=0.25)
            self.recording = False
            listener.stop()

            print(f"Recording complete! Captured {len(self.mouse_positions)} events.")
        except Exception as e:
            print(f"Listener failed with error: {e}. Falling back to polling recorder...")
            self.recording = False
            self._fallback_record_mouse_movement(duration)

        # If listener recorded nothing, use fallback polling recorder
        if not self.mouse_positions:
            print("No events captured by listener; using polling fallback recorder...")
            self._fallback_record_mouse_movement(duration)
    
    def _fallback_record_mouse_movement(self, duration: int = 5):
        """Fallback recorder that polls mouse position and button state.
        Uses Windows API via ctypes when available for click detection; otherwise
        polls `mouse_controller.position` and records moves. This is used when
        the pynput listener fails on some environments.
        """
        print("\nStarting polling-based fallback recorder...")
        start_time = time.time()
        self.mouse_positions = []

        last_pos = self._get_mouse_position()
        last_buttons = self._read_button_states()

        poll_interval = 0.02  # 50 Hz polling
        end_time = start_time + duration

        while time.time() < end_time:
            self._check_alarm()
            now = time.time()
            ts = now - start_time

            # Position
            pos = self._get_mouse_position() or last_pos

            if pos and last_pos and pos != last_pos:
                self.mouse_positions.append({
                    'type': 'move',
                    'x': int(pos[0]),
                    'y': int(pos[1]),
                    'timestamp': ts
                })
                last_pos = pos

            # Buttons (Windows only)
            if self.is_windows and last_pos:
                current_buttons = self._read_button_states()
                for name, pressed in current_buttons.items():
                    previous = last_buttons.get(name)
                    if previous is None:
                        previous = False
                    if pressed != previous:
                        self.mouse_positions.append({
                            'type': 'click',
                            'x': int(last_pos[0]),
                            'y': int(last_pos[1]),
                            'button': f'Button.{name}',
                            'pressed': pressed,
                            'timestamp': ts
                        })
                last_buttons = current_buttons

            time.sleep(poll_interval)
            self._check_alarm()

        print(f"Fallback recording complete! Captured {len(self.mouse_positions)} events.")

    def _start_alarm_thread(self) -> None:
        if self.alarm_interval_mins <= 0:
            return
        if self.alarm_thread and self.alarm_thread.is_alive():
            return
        self._alarm_stop_event.clear()
        self.alarm_thread = threading.Thread(
            target=self._alarm_worker,
            name="MouseMoverAlarm",
            daemon=True
        )
        self.alarm_thread.start()

    def _alarm_worker(self) -> None:
        interval_seconds = max(1.0, self.alarm_interval_mins * 60)
        next_beep = time.time() + interval_seconds
        while not self._alarm_stop_event.is_set():
            wait_duration = max(0.01, next_beep - time.time())
            if self._alarm_stop_event.wait(wait_duration):
                break
            self._trigger_alarm()
            next_beep += interval_seconds

    def _stop_alarm_thread(self) -> None:
        if not self.alarm_thread:
            return
        self._alarm_stop_event.set()
        self.alarm_thread.join(timeout=2.0)
        self.alarm_thread = None

    def _get_mouse_position(self) -> Optional[Tuple[int, int]]:
        try:
            pos = self.mouse_controller.position
            return (int(pos[0]), int(pos[1]))
        except Exception:
            return None

    def _win_get_async(self, key: int) -> bool:
        if not self.is_windows:
            return False
        try:
            return bool(ctypes.windll.user32.GetAsyncKeyState(key) & 0x8000)
        except Exception:
            return False

    def _read_button_states(self) -> Dict[str, bool]:
        if not self.is_windows:
            return {}
        return {name: self._win_get_async(code) for name, code in self._vk_codes.items()}

    def _has_significant_movement(
        self,
        previous: Optional[Tuple[int, int]],
        current: Optional[Tuple[int, int]],
        threshold: Optional[int] = None
    ) -> bool:
        if not previous or not current:
            return False
        th = threshold if threshold is not None else self.activity_movement_threshold
        return abs(current[0] - previous[0]) > th or abs(current[1] - previous[1]) > th

    def _buttons_changed(self, previous: Dict[str, bool], current: Dict[str, bool]) -> bool:
        for name in self._vk_codes.keys():
            if current.get(name) != previous.get(name):
                return True
        return False

    def _sleep_with_cancel(self, duration: float, step: float = 0.5) -> bool:
        if duration <= 0:
            self._check_alarm()
            return self.running
        end_time = time.time() + duration
        while self.running:
            self._check_alarm()
            now = time.time()
            if now >= end_time:
                break
            remaining = end_time - now
            sleep_chunk = max(0.01, min(step, remaining))
            time.sleep(sleep_chunk)
            self._check_alarm()
        self._check_alarm()
        return self.running

    def _trigger_alarm(self) -> None:
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[{timestamp}] Alarm interval reached - playing 1 second beep...")
        if self.is_windows and winsound is not None:
            try:
                winsound.Beep(1000, 1000)
                return
            except RuntimeError:
                pass
        # Fallback: ASCII bell + 1 second pause to mimic long beep
        print('\a', end='', flush=True)
        time.sleep(1)

    def _check_alarm(self) -> None:
        if self.alarm_interval_mins <= 0:
            return
        if not self.alarm_thread or not self.alarm_thread.is_alive():
            if not self._alarm_stop_event.is_set():
                self._start_alarm_thread()

    def wait_for_pre_replay_quiet_period(self) -> bool:
        """Enforce a brief inactivity window before replaying automation."""
        quiet_window = self.activity_window_seconds
        postpone_window = self.activity_postpone_seconds
        if quiet_window <= 0:
            self._check_alarm()
            return True

        print(
            f"Ensuring {quiet_window:.0f}-second inactivity window before replay. "
            "Move the mouse or click to delay."
        )

        while self.running:
            self._check_alarm()
            window_start = time.time()
            last_pos = self._get_mouse_position()
            last_buttons = self._read_button_states()
            quiet_period_ok = True
            activity_reason = "mouse activity"

            while self.running and (time.time() - window_start) < quiet_window:
                if not self._sleep_with_cancel(self.activity_poll_interval, step=self.activity_poll_interval):
                    return False
                current_pos = self._get_mouse_position()
                if self._has_significant_movement(last_pos, current_pos):
                    quiet_period_ok = False
                    activity_reason = "movement"
                    break

                current_buttons = self._read_button_states()
                if self._buttons_changed(last_buttons, current_buttons):
                    quiet_period_ok = False
                    activity_reason = "click"
                    break

                last_pos = current_pos
                last_buttons = current_buttons

            if quiet_period_ok:
                print("No recent activity detected. Proceeding with replay...")
                return True

            print(
                f"User {activity_reason} detected. Postponing start by {postpone_window:.0f} seconds..."
            )
            if not self._sleep_with_cancel(postpone_window, step=0.25):
                return False

        return False
        
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
        self._check_alarm()
        
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
            self._check_alarm()
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
                    self._check_alarm()
                    
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
                self._check_alarm()
            # Very brief micro-pauses (30% chance) - simulates human hesitation
            elif random.random() < 0.3 and not self.user_moved_mouse:
                time.sleep(random.uniform(0.005, 0.025))
                self._check_alarm()
        
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
            self._sleep_with_cancel(1.0, step=1.0)
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
        if self.alarm_interval_mins > 0:
            print(f"Alarm beep enabled every {self.alarm_interval_mins} minute(s).\n")
        else:
            print("Alarm beep disabled.\n")
        
        # Start grace period at the very beginning
        self.grace_period_start = time.time()
        self.grace_period_active = True
        print(f"({self.grace_period_duration}-second grace period active - user detection will start after)\n")
        
        iteration = 0
        # Main loop
        while self.running:
            self._check_alarm()
            iteration += 1
            current_time = datetime.now()
            
            # Check if we've reached the end time
            if end_time and current_time >= end_time:
                print("\nDuration limit reached. Stopping...")
                break
            
            print(f"\n[{current_time.strftime('%H:%M:%S')}] Iteration #{iteration}")
            if not self.wait_for_pre_replay_quiet_period():
                break

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

            if not self._sleep_with_cancel(wait_seconds, step=1.0):
                break
        
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

    parser.add_argument(
        '-a', '--alarm',
        type=float,
        default=0.0,
        help='Optional alarm/beep interval in minutes (set to 0 to disable)'
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.interval <= 0:
        print("Error: Interval must be greater than 0")
        return
    
    if args.duration is not None and args.duration <= 0:
        print("Error: Duration must be greater than 0")
        return

    if args.alarm < 0:
        print("Error: Alarm interval must be zero or positive")
        return
    
    # Create and run the mouse mover
    mover = MouseMover(args.interval, args.duration, args.alarm)
    
    try:
        mover.run()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user (Ctrl+C)")
    except Exception as e:
        print(f"\nError occurred: {e}")
    finally:
        mover._stop_alarm_thread()

if __name__ == "__main__":
    main()

