#!/usr/bin/env python3
"""Publish built artifacts to an explicitly selected Artifact Registry."""

import argparse
import os
import subprocess


def publish_wheel(args, run=subprocess.run):
    """Skip an existing wheel, or delete it before an explicit replacement."""
    flags = [f"--project={args.project}", f"--location={args.location}",
             f"--repository={args.prefix}-python", f"--package={args.package}"]
    found = run(["gcloud", "artifacts", "versions", "describe", args.version, *flags],
                capture_output=True, text=True)
    if found.returncode == 0:
        if not args.clobber:
            print(f"Skipping {args.package}=={args.version}: already exists")
            return
        run(["gcloud", "artifacts", "versions", "delete", args.version, *flags, "--quiet"],
            check=True)
    elif "NOT_FOUND" not in found.stderr:
        raise RuntimeError("Cannot check the existing artifact: " + found.stderr.strip())
    token = run(["gcloud", "auth", "print-access-token"],
                check=True, capture_output=True, text=True).stdout.strip()
    env = dict(os.environ)
    env.pop("UV_PUBLISH_TOKEN", None)
    env.update(UV_PUBLISH_USERNAME="oauth2accesstoken", UV_PUBLISH_PASSWORD=token)
    run(["uv", "publish", "--publish-url", args.registry, args.wheel], env=env, check=True)


def push_image(args, run=subprocess.run):
    source = f"arkhai:{args.source}-{args.suffix}"
    tags = [f"{args.registry}/arkhai:{args.target}-{args.suffix}",
            f"{args.registry}/arkhai:{args.target}"]
    for tag in tags:
        run(["docker", "tag", source, tag], check=True)
    for tag in tags:
        run(["docker", "push", tag], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "location", "prefix"):
        parser.add_argument(f"--{name}", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    wheel = commands.add_parser("wheel")
    for name in ("registry", "package", "version", "wheel"):
        wheel.add_argument(f"--{name}", required=True)
    wheel.add_argument("--clobber", action="store_true")
    image = commands.add_parser("image")
    for name in ("registry", "source", "target", "suffix"):
        image.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    for name in ("project", "location", "prefix"):
        if not getattr(args, name).strip():
            parser.error(f"AR_{name.upper()} is required")
    if args.command == "wheel":
        publish_wheel(args)
    elif args.command == "image":
        push_image(args)


if __name__ == "__main__":
    main()
