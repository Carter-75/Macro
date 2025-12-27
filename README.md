# Mouse Mover Script (Anti-Detection Mode)

An automated mouse movement script that records your mouse patterns and replays them at specified intervals with **human-like imperfections** that make detection nearly impossible.

## Features

- 🎯 **3-second countdown** before starting
- 🖱️ **5-second recording** of your mouse movements
- 💾 **Saves patterns** for reuse across runs
- 🔄 **Customizable intervals** for mouse movement
- ⏱️ **Duration control** - run for specific time or indefinitely
- ⏹️ **F10 emergency stop** - stop the script anytime
- 🔁 **Reset option** - record new patterns whenever needed
- 🤖 **Anti-Detection** - mimics human imperfections (tremor, variable timing, ease-in-out curves)
- 👤 **Human-like movement** - subtle tremor (±2px), variable speed, micro-pauses
- 🖱️ **Auto-detect manual control** - if you move the mouse yourself, it stops replay and resets the interval timer
- ⏳ **Grace period** - 5-second grace period at start and after manual control to prevent false detection
- 🚦 **Pre-start activity guard** - if you're active within 5 seconds of a planned replay, it delays the automation by 5 seconds until you're idle
- 🔔 **Optional reminder beep** - supply `-a <minutes>` to play a 1-second beep on that cadence while the script runs

## Installation

1. Install the required dependency (verified with Python 3.11, 3.12, and 3.13):
```bash
python -m pip install -r requirements.txt
```

  - On Windows you can target a specific interpreter, e.g. `py -3.12 -m pip install -r requirements.txt`.
  - The only dependency is `pynput>=1.8.1`. The 1.8.1 release (March 2025) publishes a universal `py2.py3` wheel, so pip can install it on every currently released CPython version, including 3.13, without compiling from source [^pynput-wheel]. If you are testing an alpha/beta release such as 3.14 and pip reports that no wheel is available yet, fall back to `python -m pip install pynput --no-binary :all:` to force a source install.

Or install directly:
```bash
python -m pip install "pynput>=1.8.1"
```

[^pynput-wheel]: PyPI shows a `pynput-1.8.1-py2.py3-none-any.whl` upload dated March 17, 2025, which is compatible with every supported Python 3 interpreter, including 3.13 [source](https://pypi.org/project/pynput/#files).

## Usage

### Basic Syntax
```bash
python macro.py [-i <interval_minutes>] [-d <duration_minutes>] [-a <alarm_minutes>]
```

You must supply at least one of `-i` (mouse automation) or `-a` (alarm).

### Arguments

- `-i`, `--interval` (optional but required for mouse automation): Time interval in **minutes** between mouse movements. Omit it if you just want the alarm/reminder feature.
- `-d`, `--duration` (optional): Total duration in **minutes** to run (omit for unlimited)
- `-a`, `--alarm` (optional): Interval in **minutes** for the repeating 1-second beep (set `0` to disable). You can run the script in alarm-only mode by omitting `-i` and supplying `-a`.

### Examples

**Run indefinitely, move mouse every 5 minutes:**
```bash
python macro.py -i 5
```

**Move mouse every 2 minutes for 1 hour:**
```bash
python macro.py -i 2 -d 60
```

**Move mouse every 10 minutes for 2 hours:**
```bash
python macro.py -i 10 -d 120
```

**Move mouse every 0.5 minutes (30 seconds) indefinitely:**
```bash
python macro.py -i 0.5
```

**Run with a 10-minute reminder beep alongside movement automation:**
```bash
python macro.py -i 5 -a 10
```

**Alarm-only reminder every 15 minutes (no mouse movement):**
```bash
python macro.py -a 15
```

## Replay Features 🎯

The script replays your pattern with **human-like imperfections** to avoid detection:

### Pattern Sampling
- Each replay uses approximately **85% of your recorded points**
- Randomly selects which points to skip (15% skipped for subtle variation)
- Example: If you recorded 1000 points, each replay uses ~850 points
- Very closely follows your original pattern
- Always starts and ends at the exact same place

### Anti-Detection Features 🤖
- **Hand Tremor Simulation**: ±2 pixel micro-movements during motion (like natural hand shake)
- **Ease-in-out Curves**: Smooth acceleration/deceleration instead of linear movement
- **Variable Timing**: Each movement step varies ±20% from base speed
- **Micro-Pauses**: Random brief hesitations (30% chance: 5-25ms, 15% chance: 20-150ms)
- **No Perfect Patterns**: Random sampling ensures no two replays are identical
- Makes detection by tracking software virtually impossible!

### Timing Randomness
- Movement speed matches your original recording speed (85-115% variation)
- Preserves the "feel" of your mouse movements - fast parts stay fast, slow parts stay slow
- Wait intervals randomized from **85% to 115%** of specified interval
- Example: 5-minute interval becomes 4.25 to 5.75 minutes randomly
- **15% chance of small pauses** (0.02-0.1 seconds) between points

### Smooth Human-Like Movement
- Uses ease-in-out interpolation (smooth acceleration/deceleration)
- Creates natural curves with subtle tremor, not perfect straight lines
- Variable timing prevents robotic consistency
- Looks and feels exactly like a real person moving the mouse
- Every replay follows your pattern closely but with organic human-like variations!

### User Override Detection
- **Automatically detects when you move the mouse yourself** during replay
- **5-second grace period** at the very start and after you take manual control
- Grace period prevents false detection as script starts moving
- After grace period expires, detects manual movement (>15 pixel difference)
- Instantly stops the automated movement when manual movement detected
- **Resets the interval timer** and restarts grace period for next cycle
- Lets you take control at any time without stopping the script!
- Before each replay the script now enforces a 5-second quiet window; any last-second movement or clicks delay automation by 5 seconds and restart the check

## How It Works

1. **3-second countdown** - Get ready!
2. **Pattern Selection**:
   - If a saved pattern exists, you can:
     - Press `y` to use the saved pattern
     - Press `n` to record a new pattern (overwrites saved)
     - Press `r` to reset and record a new pattern
   - If no pattern exists, records a new one automatically
3. **5-second recording** - Move your mouse around to create your movement pattern
4. **Automated replay with natural randomness** - The script replays your pattern with subtle human-like variations
5. **Press F10** at any time to stop the script

## Stopping the Script

You can stop the script in three ways:
1. **Press F10** - Clean stop at any time
2. **Ctrl+C** - Keyboard interrupt
3. **Wait for duration** - Script stops automatically if duration is set

## Taking Manual Control

You can **move your mouse at any time** during automated replay:
- **5-second grace period** at the very start and after each manual takeover
- Once grace period ends, the script actively monitors for your movement (>15 pixel change)
- Instantly stops the current replay when you move the mouse
- **Resets the interval timer** and starts counting fresh
- **Restarts the 5-second grace period** for the next cycle
- You regain full control immediately
- Script continues running in the background and will replay after the next interval

## Alarm Reminder (Optional)

- Enable with `-a <minutes>` to play a **1-second, normal-volume beep** on your chosen cadence
- Omit `-i` if you only need the alarm/reminder and do not want mouse automation
- The reminder timer runs independently of mouse automation, so it will fire even while the script is replaying patterns or waiting for the next interval
- For alarm intervals of at least 1 minute, the script announces the remaining minutes each minute (e.g., "9 minute(s) left", then "8 minute(s) left") until the next beep
- User activity cannot postpone the beep schedule; it will trigger exactly on the cadence you specify
- On Windows the script first emits a dual-tone `winsound.Beep` (1500 Hz for 0.75s, then 1000 Hz for 0.5s) so the reminder is loud enough to cut through fullscreen audio. The quieter system alert fallback only triggers if the Beep API fails, so you will not hear both. On other platforms it emits an ASCII bell followed by a 1-second pause to mimic the same effect

## Pattern File

- Patterns are saved in `mouse_pattern.json`
- The file stores mouse positions and timing information
- Delete this file to start fresh on the next run

## Tips

- **Recording**: During the 5-second recording, create a natural mouse movement pattern - the script will replay it with human-like imperfections
- **Pattern Fidelity**: Uses 85% of your recorded points + adds tremor and timing variations
- **Anti-Detection**: The tremor (±2px) and variable timing make it virtually undetectable by tracking software
- **Grace Period**: 5-second grace period at start and after manual control prevents false detection
- **Manual Override**: Just move your mouse during replay (after grace period ends) to take control - the interval timer resets automatically
- **Interval**: Choose a base interval (e.g., 5 minutes) - actual timing will vary ±15% automatically for natural feel
- **Duration**: Use unlimited mode for all-day tasks, or set a specific duration for timed activities
- **F10 Key**: Keep in mind that F10 is your emergency stop - it works even if the terminal isn't focused

## Use Cases

- Prevent screen lock during presentations
- Keep communication apps showing "active" status
- Prevent screensaver activation during long-running tasks
- Automated testing scenarios

## Notes

- The script uses the `pynput` library for cross-platform mouse and keyboard control
- Mouse positions are recorded as a base pattern, then replayed with ~85% of points
- **Anti-Detection Features:**
  - Hand tremor: ±2 pixel micro-movements during motion
  - Ease-in-out curves: Smooth acceleration/deceleration (not linear)
  - Variable timing: Each step varies ±20% from base speed
  - Micro-pauses: Random hesitations (30% brief, 15% longer)
  - Random point sampling: No two replays are identical
- **User movement detection**: 5-second grace period at start and after manual control
- Grace period only happens twice: (1) at the very beginning, (2) after you take manual control
- After grace period ends, checks for >20 pixel difference to detect manual control (accounts for tremor)
- When you take manual control, the interval timer resets, grace period restarts for next cycle
- The F10 listener works globally (even when the terminal isn't focused)
- Movement looks and behaves like a real human moving the mouse
- Virtually undetectable by tracking software due to realistic imperfections

---

**Remember**: Use responsibly and in accordance with your workplace/system policies! 🎯

