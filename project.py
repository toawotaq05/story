#!/usr/bin/env python3
"""Manage named story projects under workspace/."""
import argparse
import os
import sys

from paths import (
    CURRENT_PROJECT_FILE,
    DEFAULT_PROJECTS_DIR,
    PROJECT_DIR,
    ensure_runtime_dirs,
    get_current_project_name,
    set_current_project_name,
)


def project_dir(name):
    return os.path.join(DEFAULT_PROJECTS_DIR, name)


def list_projects():
    os.makedirs(DEFAULT_PROJECTS_DIR, exist_ok=True)
    current = get_current_project_name()
    names = []
    for entry in sorted(os.listdir(DEFAULT_PROJECTS_DIR)):
        path = os.path.join(DEFAULT_PROJECTS_DIR, entry)
        if entry.startswith("."):
            continue
        if os.path.isdir(path):
            names.append(entry)

    if not names:
        print("No projects found.")
        return

    for name in names:
        marker = "*" if name == current else " "
        print(f"{marker} {name}  {project_dir(name)}")


def create_project(name, switch=False):
    path = project_dir(name)
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "chapters"), exist_ok=True)
    os.makedirs(os.path.join(path, "artifacts", "raw"), exist_ok=True)
    if switch:
        set_current_project_name(name)
    print(path)


def use_project(name):
    path = project_dir(name)
    if not os.path.isdir(path):
        print(f"ERROR: Project not found: {name}")
        sys.exit(1)
    set_current_project_name(name)
    print(path)


def main():
    parser = argparse.ArgumentParser(description="Manage named story projects")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Create a new project")
    init_parser.add_argument("name", help="Project name")
    init_parser.add_argument(
        "--no-switch",
        action="store_true",
        help="Create the project without making it current",
    )

    use_parser = subparsers.add_parser("use", help="Switch current project")
    use_parser.add_argument("name", help="Project name")

    subparsers.add_parser("list", help="List projects")
    subparsers.add_parser("current", help="Show current project")
    subparsers.add_parser("path", help="Show active project path")

    args = parser.parse_args()

    if args.command == "init":
        create_project(args.name, switch=not args.no_switch)
        return
    if args.command == "use":
        use_project(args.name)
        return
    if args.command == "list":
        list_projects()
        return
    if args.command == "current":
        print(get_current_project_name())
        return
    if args.command == "path":
        ensure_runtime_dirs()
        print(PROJECT_DIR)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
