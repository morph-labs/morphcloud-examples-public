#!/usr/bin/env python3
"""
Extract game state information from Pokemon EVA framework logs.

This script parses JSONL formatted log files and extracts only the lines
that contain game state information, writing the game state value to a 
new file for easier analysis. It also extracts all visited locations in order.
"""

import json
import sys
import os
import argparse
import re
from datetime import datetime

def extract_location_from_game_state(game_state):
    """
    Extract location information from a game state string.
    
    Args:
        game_state (str): The game state string
        
    Returns:
        tuple: (location, coordinates) or (None, None) if not found
    """
    location_match = re.search(r"Location:\s*([^\n]+)", game_state)
    coordinates_match = re.search(r"Coordinates:\s*([^\n]+)", game_state)
    
    location = location_match.group(1).strip() if location_match else None
    coordinates = coordinates_match.group(1).strip() if coordinates_match else None
    
    return (location, coordinates)

def extract_game_states(log_file_path, output_dir=None, timestamp=True):
    """
    Extract game state information from a log file.
    
    Args:
        log_file_path (str): Path to the log file
        output_dir (str): Directory for output files (None for current directory)
        timestamp (bool): Whether to include timestamps in output
        
    Returns:
        int: Number of game states extracted
    """
    count = 0
    locations = []
    location_timestamps = []
    steps = set()  # To track unique step indices
    
    # Track session time
    first_timestamp = None
    last_timestamp = None
    
    base_name = os.path.basename(log_file_path)
    file_name, ext = os.path.splitext(base_name)
    
    # Create output directory if specified
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{file_name}_game_states.txt")
        locations_file = os.path.join(output_dir, f"{file_name}_locations.txt")
        summary_file = os.path.join(output_dir, f"{file_name}_summary.txt")
    else:
        output_file = f"{file_name}_game_states.txt"
        locations_file = f"{file_name}_locations.txt"
        summary_file = f"{file_name}_summary.txt"
    
    try:
        with open(log_file_path, 'r') as f_in:
            with open(output_file, 'w') as f_out:
                for line_num, line in enumerate(f_in, 1):
                    try:
                        # Parse JSON line
                        log_entry = json.loads(line)
                        
                        # Track first and last timestamps for session duration
                        if "timestamp" in log_entry:
                            try:
                                current_ts = datetime.fromisoformat(log_entry["timestamp"].replace('Z', '+00:00'))
                                if first_timestamp is None:
                                    first_timestamp = current_ts
                                last_timestamp = current_ts
                            except (ValueError, TypeError):
                                pass
                                
                        # Track step indices
                        if "step_index" in log_entry:
                            steps.add(log_entry["step_index"])
                        
                        # Only process lines with game_state
                        if "game_state" in log_entry:
                            count += 1
                            game_state = log_entry['game_state']
                            
                            # Extract location data for the locations summary
                            location, coords = extract_location_from_game_state(game_state)
                            if location:
                                # Add timestamp if available
                                time_str = None
                                if "timestamp" in log_entry:
                                    try:
                                        ts = datetime.fromisoformat(log_entry["timestamp"].replace('Z', '+00:00'))
                                        time_str = ts.strftime("%Y-%m-%d %H:%M:%S")
                                    except (ValueError, TypeError):
                                        time_str = log_entry.get("timestamp", "Unknown")
                                
                                # Add to locations list if it's a new location or first entry
                                if not locations or locations[-1] != location:
                                    locations.append(location)
                                    location_timestamps.append(time_str)
                            
                            # Format the output for game states file
                            if timestamp and "timestamp" in log_entry:
                                try:
                                    # Parse ISO timestamp to more readable format
                                    ts = datetime.fromisoformat(log_entry["timestamp"].replace('Z', '+00:00'))
                                    time_str = ts.strftime("%Y-%m-%d %H:%M:%S")
                                except (ValueError, TypeError):
                                    time_str = log_entry.get("timestamp", "Unknown")
                                
                                f_out.write(f"[{time_str}] Game State #{count}:\n")
                            else:
                                f_out.write(f"Game State #{count}:\n")
                            
                            # Write the game state content
                            f_out.write(f"{game_state}\n\n")
                            
                    except json.JSONDecodeError:
                        sys.stderr.write(f"Warning: Invalid JSON at line {line_num}\n")
                    except Exception as e:
                        sys.stderr.write(f"Error processing line {line_num}: {str(e)}\n")
        
        # Write locations to a separate file
        with open(locations_file, 'w') as f_loc:
            f_loc.write("LOCATIONS VISITED (in order):\n")
            f_loc.write("==========================\n\n")
            for i, (location, time_str) in enumerate(zip(locations, location_timestamps), 1):
                if time_str:
                    f_loc.write(f"{i}. [{time_str}] {location}\n")
                else:
                    f_loc.write(f"{i}. {location}\n")
                    
        # Calculate session duration
        duration_str = "Unknown"
        if first_timestamp and last_timestamp:
            duration = last_timestamp - first_timestamp
            hours, remainder = divmod(duration.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            duration_str = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
            
        # Write summary information
        with open(summary_file, 'w') as f_sum:
            f_sum.write("SESSION SUMMARY\n")
            f_sum.write("==============\n\n")
            
            if first_timestamp:
                f_sum.write(f"Start Time: {first_timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            if last_timestamp:
                f_sum.write(f"End Time: {last_timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            
            f_sum.write(f"Session Duration: {duration_str}\n")
            f_sum.write(f"Total Steps: {max(steps) if steps else 0}\n")
            f_sum.write(f"Game States Recorded: {count}\n")
            f_sum.write(f"Unique Locations Visited: {len(set(locations))}\n\n")
            
            f_sum.write("Locations (alphabetical):\n")
            for loc in sorted(set(locations)):
                f_sum.write(f"- {loc}\n")
    
        # Print summary information to stdout
        print(f"\nSESSION SUMMARY:")
        print(f"==============")
        print(f"Start Time: {first_timestamp.strftime('%Y-%m-%d %H:%M:%S') if first_timestamp else 'Unknown'}")
        print(f"End Time: {last_timestamp.strftime('%Y-%m-%d %H:%M:%S') if last_timestamp else 'Unknown'}")
        print(f"Session Duration: {duration_str}")
        print(f"Total Steps: {max(steps) if steps else 0}")
        print(f"Game States Recorded: {count}")
        print(f"Unique Locations Visited: {len(set(locations))}")
        
        print(f"\nOutputs saved to:")
        print(f"- {output_file}")
        print(f"- {locations_file}")
        print(f"- {summary_file}")
        
        print("\nUNIQUE LOCATIONS VISITED:")
        print("=======================")
        for i, location in enumerate(sorted(set(locations)), 1):
            print(f"{i}. {location}")
            
        return count
    
    except FileNotFoundError:
        sys.stderr.write(f"Error: File not found: {log_file_path}\n")
        return 0
    except Exception as e:
        sys.stderr.write(f"Error: {str(e)}\n")
        return 0

def main():
    parser = argparse.ArgumentParser(description='Extract game states from Pokemon EVA logs')
    parser.add_argument('log_file', help='Path to the log file')
    parser.add_argument('-o', '--output-dir', default='evaluated', 
                        help='Output directory (default: "evaluated/")')
    parser.add_argument('--no-timestamp', action='store_true', help='Exclude timestamps in output')
    
    args = parser.parse_args()
    
    extract_game_states(
        args.log_file,
        args.output_dir,
        not args.no_timestamp
    )

if __name__ == "__main__":
    main()
