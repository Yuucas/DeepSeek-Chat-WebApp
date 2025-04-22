import os
import argparse

base_path = r"C:\Users\yukse\Desktop\Yuksel\Yucas\Computer_Vision\Akgida_Cap_Control\app"

def combine_python_files(file_paths, output_file):

    try:
        with open(output_file, 'w') as outfile:
            for file_path in file_paths:
                try:
                    with open(file_path, 'r') as infile:
                        print(file_path)
                        outfile.write("================================================\n")
                        outfile.write(f"File: {file_path}\n")
                        outfile.write("================================================\n")
                        outfile.write(infile.read())
                        outfile.write("\n\n")

                except FileNotFoundError:
                    print(f"Error: File not found: {file_path}")
                    return
                except Exception as e:
                    print(f"Error reading file {file_path}: {e}")
                    return

        print(f"Files combined successfully into: {output_file}")

    except Exception as e:
        print(f"An error occurred while writing to the output file: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Combine Python files into a single file.")
    parser.add_argument("files", nargs="+", help="Paths to the Python files.")
    parser.add_argument("-o", "--output", default="combined_file.txt", help="Path to the output file.")

    args = parser.parse_args()

    combine_python_files(args.files, args.output)