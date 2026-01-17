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
        interval_mins: Optional[float] = None,
        duration_mins: Optional[float] = None,
        alarm_interval_mins: float = 0.0,
        track_keys: bool = False
    ):
        self.interval_mins = interval_mins
        self.duration_mins = duration_mins
        self.pattern_file = "mouse_pattern.json"
        self.mouse_positions: List[Dict[str, Any]] = []
        self.track_keys = track_keys
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

        # For key replay
        self.held_modifiers = set()

        # For anti-detection
        self.pattern_center_x = 0.0
        self.pattern_center_y = 0.0

    def _test_keyboard_listener(self) -> bool:
        if not self.track_keys:
            return True
        print("[KEYBOARD TEST] Testing keyboard listener...")
        try:
            keyboard_listener = keyboard.Listener(on_press=lambda key: None, on_release=lambda key: None)
            keyboard_listener.start()
            time.sleep(0.1)
            keyboard_listener.stop()
            print("[KEYBOARD TEST] ✓ Keyboard listener works!")
            return True
        except Exception as e:
            print(f"[KEYBOARD TEST] ✗ Keyboard listener failed: {type(e).__name__}: {e}")
            print("[KEYBOARD TEST] WARNING: Key tracking will not work. Continuing without key tracking...")
            self.track_keys = False
            return False

    def record_mouse_movement(self, duration: int = 5):
        self._test_keyboard_listener()
        print(f"\nRecording mouse movement and clicks for {duration} seconds...")
        print("Recording starts in:")
        for i in range(3, 0, -1):
            print(f"{i}...")
            self._sleep_with_cancel(1.0, step=1.0)
        print("GO! Move your mouse and click around to create a pattern!")
        self._fallback_record_mouse_movement(duration)

    def _fallback_record_mouse_movement(self, duration: int = 5):
        print("\nStarting polling-based fallback recorder...")
        start_time = time.time()
        self.mouse_positions = []
        last_pos = self._get_mouse_position()
        last_buttons = self._read_button_states()

        keyboard_listener = None
        key_events = {}
        if self.track_keys:
            try:
                def on_key_press(key: Any):
                    elapsed = time.time() - start_time
                    key_name = key.char if hasattr(key, 'char') and key.char else str(key).split('.')[-1]
                    if key_name not in key_events or not key_events[key_name].get('pressed'):
                        self.mouse_positions.append({
                            'type': 'key',
                            'key': key_name,
                            'pressed': True,
                            'timestamp': elapsed
                        })
                        key_events[key_name] = {'pressed': True, 'time': elapsed}

                def on_key_release(key: Any):
                    elapsed = time.time() - start_time
                    key_name = key.char if hasattr(key, 'char') and key.char else str(key).split('.')[-1]
                    if key_name in key_events and key_events[key_name].get('pressed'):
                        self.mouse_positions.append({
                            'type': 'key',
                            'key': key_name,
                            'pressed': False,
                            'timestamp': elapsed
                        })
                        key_events[key_name] = {'pressed': False, 'time': elapsed}

                keyboard_listener = keyboard.Listener(on_press=on_key_press, on_release=on_key_release)
                keyboard_listener.start()
                print("[INFO] Keyboard listener active - key presses will be recorded")
            except Exception as kb_error:
                print(f"[WARNING] Keyboard listener failed: {type(kb_error).__name__}: {kb_error}")
                self.track_keys = False

        poll_interval = 0.02
        end_time = start_time + duration
        while time.time() < end_time:
            self._check_alarm()
            now = time.time()
            ts = now - start_time
            pos = self._get_mouse_position() or last_pos
            if pos and last_pos and pos != last_pos:
                self.mouse_positions.append({
                    'type': 'move',
                    'x': int(pos[0]),
                    'y': int(pos[1]),
                    'timestamp': ts
                })
                last_pos = pos

            if self.is_windows and last_pos:
                current_buttons = self._read_button_states()
                for name, pressed in current_buttons.items():
                    previous = last_buttons.get(name, False)
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

        if keyboard_listener:
            keyboard_listener.stop()
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
        while not self._alarm_stop_event.is_set():
            remaining_interval = interval_seconds
            full_minutes = int(remaining_interval // 60)
            for minutes_remaining in range(full_minutes, 0, -1):
                if self._alarm_stop_event.wait(60):
                    return
                remaining_interval -= 60
                minutes_left_after_wait = minutes_remaining - 1
                timestamp = datetime.now().strftime('%H:%M:%S')
                if minutes_left_after_wait > 0:
                    print(f"[{timestamp}] Alarm beep in {minutes_left_after_wait} minute(s)...")
                else:
                    print(f"[{timestamp}] Alarm beep in <1 minute...")
            if remaining_interval > 0:
                if self._alarm_stop_event.wait(remaining_interval):
                    return
            if self._alarm_stop_event.is_set():
                break
            self._trigger_alarm()

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
        played_sound = False
        if self.is_windows and winsound is not None:
            try:
                winsound.Beep(1500, 750)
                winsound.Beep(1000, 500)
                played_sound = True
            except RuntimeError:
                pass
            if not played_sound:
                alias_flags = winsound.SND_ALIAS | winsound.SND_ASYNC
                for alias in ('SystemHand', 'SystemExclamation', 'SystemAsterisk'):
                    try:
                        winsound.PlaySound(alias, alias_flags)
                        time.sleep(1)
                        winsound.PlaySound(None, 0)
                        played_sound = True
                        break
                    except RuntimeError:
                        continue
                if played_sound:
                    return
        print('\a', end='', flush=True)
        time.sleep(1)

    def _check_alarm(self) -> None:
        if self.alarm_interval_mins <= 0:
            return
        if not self.alarm_thread or not self.alarm_thread.is_alive():
            if not self._alarm_stop_event.is_set():
                self._start_alarm_thread()

    def wait_for_pre_replay_quiet_period(self) -> bool:
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
        with open(self.pattern_file, 'w') as f:
            json.dump(self.mouse_positions, f)
        print(f"Pattern saved to {self.pattern_file}")

    def load_pattern(self):
        try:
            with open(self.pattern_file, 'r') as f:
                self.mouse_positions = json.load(f)
            # Compute center only from valid x/y entries
            xs = [p['x'] for p in self.mouse_positions if 'x' in p and isinstance(p['x'], (int, float))]
            ys = [p['y'] for p in self.mouse_positions if 'y' in p and isinstance(p['y'], (int, float))]
            if xs and ys:
                self.pattern_center_x = sum(xs) / len(xs)
                self.pattern_center_y = sum(ys) / len(ys)
            else:
                self.pattern_center_x = self.pattern_center_y = 0.0
            print(f"Loaded pattern with {len(self.mouse_positions)} positions. Center: ({self.pattern_center_x:.1f}, {self.pattern_center_y:.1f})")
            return True
        except FileNotFoundError:
            print("No saved pattern found.")
            return False
        except Exception as e:
            print(f"Error loading pattern: {e}")
            return False

    def replay_pattern(self):
        if not self.mouse_positions:
            print("No pattern to replay!")
            return

        print("Replaying mouse pattern with human-like imperfections...")
        self.currently_replaying = True
        self.user_moved_mouse = False
        self._check_alarm()

        # Anti-detection variation
        if random.random() < 0.92:
            global_offset_x = random.randint(-80, 80)
            global_offset_y = random.randint(-60, 60)
            scale = random.uniform(0.94, 1.06)
        else:
            global_offset_x = global_offset_y = 0
            scale = 1.0

        selected_points = []
        total_points = len(self.mouse_positions)
        for i, pos in enumerate(self.mouse_positions):
            is_click = pos.get('type') == 'click'
            if is_click or i == 0 or i == total_points - 1 or random.random() < 0.85:
                selected_points.append(pos)

        print(f"Selected {len(selected_points)} points from {total_points} (~{len(selected_points)/total_points*100:.1f}%)")

        prev_timestamp = 0.0
        self.held_modifiers = set()

        for pos in selected_points:
            self._check_alarm()
            if not self.running or self.user_moved_mouse:
                if self.user_moved_mouse:
                    print("\n⚠️ User mouse movement detected! Stopping replay and resetting interval...")
                break

            # Position handling only for events with coordinates
            target_x = target_y = None
            if pos.get('type') in ('move', 'click') and 'x' in pos and 'y' in pos:
                scaled_x = (pos['x'] - self.pattern_center_x) * scale + self.pattern_center_x
                scaled_y = (pos['y'] - self.pattern_center_y) * scale + self.pattern_center_y
                target_x = int(scaled_x + global_offset_x)
                target_y = int(scaled_y + global_offset_y)
                target_x = max(0, min(target_x, 3840))
                target_y = max(0, min(target_y, 2160))

            current_timestamp = pos['timestamp']
            time_to_move = current_timestamp - prev_timestamp

            # Movement logic only when we have a valid target
            if target_x is not None and target_y is not None:
                if time_to_move > 0:
                    time_variation = random.uniform(0.85, 1.15)
                    time_to_move *= time_variation

                    current_x, current_y = self.mouse_controller.position
                    distance = ((target_x - current_x) ** 2 + (target_y - current_y) ** 2) ** 0.5
                    steps = max(5, int(distance / 30))
                    base_sleep_per_step = time_to_move / steps if steps > 0 else 0.001

                    for step in range(steps):
                        if not self.running or self.user_moved_mouse:
                            if self.user_moved_mouse:
                                print("\n⚠️ User mouse movement detected! Stopping replay and resetting interval...")
                            break

                        progress = (step + 1) / steps
                        eased_progress = progress * progress * (3.0 - 2.0 * progress)

                        expected_x = int(current_x + (target_x - current_x) * eased_progress)
                        expected_y = int(current_y + (target_y - current_y) * eased_progress)

                        tremor_x = random.randint(-2, 2)
                        tremor_y = random.randint(-2, 2)
                        actual_x = expected_x + tremor_x
                        actual_y = expected_y + tremor_y

                        self.mouse_controller.position = (actual_x, actual_y)

                        sleep_variation = random.uniform(0.8, 1.2)
                        time.sleep(base_sleep_per_step * sleep_variation)
                        self._check_alarm()

                        if self.grace_period_active and self.grace_period_start is not None:
                            if time.time() - self.grace_period_start > self.grace_period_duration:
                                self.grace_period_active = False
                                print("(Grace period ended - user detection now active)")

                        if not self.grace_period_active:
                            cx, cy = self.mouse_controller.position
                            if abs(cx - actual_x) > 20 or abs(cy - actual_y) > 20:
                                self.user_moved_mouse = True
                                break
                else:
                    self.mouse_controller.position = (target_x, target_y)
            elif time_to_move > 0:
                # Preserve timing for key events
                time.sleep(time_to_move * random.uniform(0.85, 1.15))

            # Click handling
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

            # Key handling
            if pos.get('type') == 'key':
                key_str = pos['key']
                try:
                    kb = keyboard.Controller()
                    is_pressed = pos['pressed']

                    modifiers = {
                        'shift': keyboard.Key.shift,
                        'ctrl': keyboard.Key.ctrl,
                        'alt': keyboard.Key.alt,
                        'cmd': keyboard.Key.cmd,
                    }

                    if key_str in modifiers:
                        mod_key = modifiers[key_str]
                        if is_pressed:
                            kb.press(mod_key)
                            self.held_modifiers.add(key_str)
                        else:
                            kb.release(mod_key)
                            self.held_modifiers.discard(key_str)

                    elif key_str.startswith('Key.'):
                        key_name = key_str.split('.')[-1]
                        special_keys = {
                            'enter': keyboard.Key.enter,
                            'backspace': keyboard.Key.backspace,
                            'space': keyboard.Key.space,
                            'tab': keyboard.Key.tab,
                            'esc': keyboard.Key.esc,
                            'up': keyboard.Key.up,
                            'down': keyboard.Key.down,
                            'left': keyboard.Key.left,
                            'right': keyboard.Key.right,
                            'delete': keyboard.Key.delete,
                            'page_up': keyboard.Key.page_up,
                            'page_down': keyboard.Key.page_down,
                            'home': keyboard.Key.home,
                            'end': keyboard.Key.end,
                            'f1': keyboard.Key.f1,
                            'f2': keyboard.Key.f2,
                            'f3': keyboard.Key.f3,
                            'f4': keyboard.Key.f4,
                            'f5': keyboard.Key.f5,
                            'f6': keyboard.Key.f6,
                            'f7': keyboard.Key.f7,
                            'f8': keyboard.Key.f8,
                            'f9': keyboard.Key.f9,
                            'f10': keyboard.Key.f10,
                            'f11': keyboard.Key.f11,
                            'f12': keyboard.Key.f12,
                        }
                        if key_name in special_keys:
                            key_obj = special_keys[key_name]
                            if is_pressed:
                                kb.press(key_obj)
                            else:
                                kb.release(key_obj)

                    else:
                        if is_pressed and len(key_str) == 1:
                            time.sleep(random.uniform(0.045, 0.22))
                            if random.random() < 0.18:
                                continue
                            try:
                                kb.press(key_str)
                                time.sleep(random.uniform(0.01, 0.04))
                                kb.release(key_str)
                            except:
                                kb.type(key_str)
                except Exception:
                    pass

            prev_timestamp = current_timestamp

            if random.random() < 0.15 and not self.user_moved_mouse:
                time.sleep(random.uniform(0.02, 0.15))
                self._check_alarm()
            elif random.random() < 0.3 and not self.user_moved_mouse:
                time.sleep(random.uniform(0.005, 0.025))
                self._check_alarm()

        self.currently_replaying = False
        if not self.user_moved_mouse:
            print("Pattern replay complete!")

    def setup_keyboard_listener(self):
        def on_press(key: Any):
            try:
                if key == keyboard.Key.f10:
                    print("\n\nF10 pressed! Stopping script...")
                    self.running = False
                    return False
            except AttributeError:
                pass
            return None

        listener = keyboard.Listener(on_press=on_press)
        listener.start()
        return listener

    def _run_alarm_only(self) -> None:
        if self.alarm_interval_mins <= 0:
            print("No interval or alarm specified. Nothing to do.")
            return
        print("\nAlarm-only mode enabled (no mouse automation configured).")
        self.setup_keyboard_listener()
        end_time = None
        if self.duration_mins:
            end_time = datetime.now() + timedelta(minutes=self.duration_mins)
            print(f"Running alarm for {self.duration_mins} minute(s) (until {end_time.strftime('%H:%M:%S')})")
        else:
            print("Running alarm indefinitely (press F10 to stop)")
        print(f"Playing 1-second beep every {self.alarm_interval_mins} minute(s).\n")
        while self.running:
            self._check_alarm()
            if end_time and datetime.now() >= end_time:
                print("\nDuration limit reached. Stopping alarm...")
                break
            if not self._sleep_with_cancel(1.0, step=1.0):
                break
        print("\n" + "=" * 50)
        print("Script stopped!")
        print("=" * 50)

    def run(self):
        print("=" * 50)
        print("MOUSE MOVER SCRIPT (ANTI-DETECTION MODE)")
        print("=" * 50)
        has_interval = bool(self.interval_mins and self.interval_mins > 0)
        if not has_interval:
            self._run_alarm_only()
            return

        pattern_exists = os.path.exists(self.pattern_file)

        if pattern_exists:
            choice = input("Saved pattern found. Use it? (y/n) or 'r' to reset: ").lower()
            if choice == 'r':
                print("Resetting pattern...")
                self.record_mouse_movement(5)
                self.save_pattern()
                self.load_pattern()  # Load to compute center
                self.grace_period_duration = 5.0
            elif choice == 'y':
                self.load_pattern()
                self.grace_period_duration = 0.5
            else:
                self.record_mouse_movement(5)
                self.save_pattern()
                self.load_pattern()
                self.grace_period_duration = 5.0
        else:
            print("No saved pattern found. Recording new pattern...")
            self.record_mouse_movement(5)
            self.save_pattern()
            self.load_pattern()  # Load to compute center
            self.grace_period_duration = 5.0

        if not self.mouse_positions:
            print("No pattern available. Exiting.")
            return

        print("\nStarting in 3 seconds...")
        for i in range(3, 0, -1):
            print(f"{i}...")
            self._sleep_with_cancel(1.0, step=1.0)
        print("Starting!\n")

        self.setup_keyboard_listener()

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

        self.grace_period_start = time.time()
        self.grace_period_active = True
        print(f"({self.grace_period_duration}-second grace period active - user detection will start after)\n")

        iteration = 0
        while self.running:
            self._check_alarm()
            iteration += 1
            current_time = datetime.now()

            if end_time and current_time >= end_time:
                print("\nDuration limit reached. Stopping...")
                break

            print(f"\n[{current_time.strftime('%H:%M:%S')}] Iteration #{iteration}")
            if not self.wait_for_pre_replay_quiet_period():
                break
            self.replay_pattern()

            if not self.running:
                break

            if self.user_moved_mouse:
                print("Interval timer reset! Waiting full interval before next replay...")
                self.user_moved_mouse = False
                self.grace_period_start = time.time()
                self.grace_period_active = True
                print(f"({self.grace_period_duration}-second grace period restarted after manual control)\n")

            random_variation = random.uniform(0.85, 1.15)
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
        description="Automated mouse mover - records and replays mouse patterns with human-like imperfections",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mouse_mover.py -i 5
  python mouse_mover.py -i 2 -d 60
  python mouse_mover.py -i 10 -d 120
  python mouse_mover.py -a 15
  python mouse_mover.py -a 10 -k -i 5
        """
    )
    parser.add_argument('-i', '--interval', type=float, default=None,
                        help='Interval in minutes between movements')
    parser.add_argument('-d', '--duration', type=float, default=None,
                        help='Total run duration in minutes')
    parser.add_argument('-a', '--alarm', type=float, default=0.0,
                        help='Alarm interval in minutes')
    parser.add_argument('-k', '--track-keys', action='store_true',
                        help='Enable keyboard tracking and replay')

    args = parser.parse_args()

    if args.interval is not None and args.interval <= 0:
        print("Error: Interval must be greater than 0")
        return
    if args.duration is not None and args.duration <= 0:
        print("Error: Duration must be greater than 0")
        return
    if args.alarm < 0:
        print("Error: Alarm must be >= 0")
        return
    if args.interval is None and args.alarm <= 0:
        print("Error: Provide either --interval or a positive --alarm")
        return

    mover = MouseMover(args.interval, args.duration, args.alarm, args.track_keys)

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