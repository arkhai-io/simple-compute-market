#!/usr/bin/env python3
"""Python script to build the Market C extension binding"""

import sys
import os
import subprocess
import shutil
from pathlib import Path

def find_pufferlib_env_binding():
    """Try to find pufferlib's env_binding.h"""
    try:
        import pufferlib
        pufferlib_path = Path(pufferlib.__file__).parent
        
        # Common locations for env_binding.h in installed pufferlib
        possible_paths = [
            pufferlib_path / "ocean" / "env_binding.h",
            pufferlib_path.parent / "ocean" / "env_binding.h",
            Path(pufferlib.__file__).parent.parent / "pufferlib" / "ocean" / "env_binding.h",
        ]
        
        # Also check if pufferlib is installed from source (editable install)
        # Look in the parent directories for a source installation
        current = Path(pufferlib.__file__).parent
        for _ in range(5):  # Check up to 5 levels up
            ocean_path = current / "ocean" / "env_binding.h"
            if ocean_path.exists():
                return str(ocean_path)
            current = current.parent
        
        # Check installed site-packages locations
        for path in possible_paths:
            if path.exists():
                return str(path)
            
    except ImportError:
        pass
    
    # Try to find it via Python's import system
    try:
        import importlib.util
        spec = importlib.util.find_spec("pufferlib.ocean")
        if spec and spec.origin:
            ocean_dir = Path(spec.origin).parent
            env_binding = ocean_dir / "env_binding.h"
            if env_binding.exists():
                return str(env_binding)
    except Exception:
        pass
    
    return None

def build_extension():
    """Build the C extension"""
    env_dir = Path(__file__).parent
    
    print("=" * 60)
    print("Building Market C Extension Binding")
    print("=" * 60)
    
    # Check for env_binding.h
    env_binding_h = find_pufferlib_env_binding()
    if env_binding_h:
        print(f"✓ Found env_binding.h at: {env_binding_h}")
        # Copy to parent directory (binding.c expects ../env_binding.h)
        parent_binding_h = env_dir.parent / "env_binding.h"
        if not parent_binding_h.exists() or Path(env_binding_h).stat().st_mtime > parent_binding_h.stat().st_mtime:
            shutil.copy2(env_binding_h, parent_binding_h)
            print(f"  Copied to: {parent_binding_h}")
    else:
        print("⚠ env_binding.h not found")
        print("  This file is required from pufferlib's build system.")
        print("  Options:")
        print("  1. Install pufferlib from source (recommended):")
        print("     git clone https://github.com/pufferai/pufferlib")
        print("     cd pufferlib")
        print("     uv pip install -e .")
        print("  2. Or manually copy env_binding.h to the app/ directory")
        print("  3. Or install pufferlib in editable mode if you have the source")
        return False
    
    # Check if we have the necessary files
    required_files = ["binding.c", "market.c", "market.h"]
    missing_files = [f for f in required_files if not (env_dir / f).exists()]
    
    if missing_files:
        print(f"✗ Missing required files: {missing_files}")
        return False
    
    print(f"\n✓ All required files found")
    
    # Try to build using setuptools/distutils
    print("\nBuilding extension...")
    try:
        from distutils.core import setup, Extension
        from distutils.command.build_ext import build_ext
        
        # The binding.c expects ../env_binding.h, so we need to adjust include paths
        app_dir = env_dir.parent
        project_root = app_dir.parent
        
        # Get numpy include directory
        try:
            import numpy
            numpy_include = numpy.get_include()
        except ImportError:
            numpy_include = None
        
        include_dirs = [
            str(env_dir),      # For market.h
            str(app_dir),      # For ../env_binding.h (relative to binding.c)
        ]
        if numpy_include:
            include_dirs.append(numpy_include)
        
        # Only compile binding.c - it includes market.h which has all implementations
        # market.c is just a test file, not needed for the extension
        ext = Extension(
            'binding',  # Simple name - will be built in current directory
            sources=[
                str(env_dir / 'binding.c'),
                # Don't include market.c - it's just a test file
                # binding.c includes market.h which has all the code
            ],
            include_dirs=include_dirs,
            extra_compile_args=['-O3', '-std=c11'],
        )
        
        # Build from the environment directory to avoid package discovery issues
        original_dir = os.getcwd()
        os.chdir(env_dir)
        
        try:
            # Use distutils to build - simpler and avoids package discovery
            setup(
                name='market-binding',
                ext_modules=[ext],
                script_args=['build_ext', '--inplace'],
            )
            print("\n✓ Build successful!")
            
            # Check if the .so file was created
            so_files = list(env_dir.glob("binding*.so"))
            if so_files:
                print(f"  Created: {so_files[0].name}")
                print(f"  Location: {so_files[0]}")
            else:
                print("  ⚠ Warning: .so file not found in expected location")
                # Check in build directory
                build_dir = env_dir / "build"
                if build_dir.exists():
                    for so_file in build_dir.rglob("binding*.so"):
                        print(f"  Found in build dir: {so_file}")
                        # Copy to environment directory
                        target = env_dir / so_file.name
                        shutil.copy2(so_file, target)
                        print(f"  Copied to: {target}")
            
            return True
        finally:
            os.chdir(original_dir)
            
    except Exception as e:
        print(f"\n✗ Build failed: {e}")
        import traceback
        traceback.print_exc()
        print("\nTroubleshooting:")
        print("  1. Ensure you have gcc/clang installed")
        print("  2. Ensure pufferlib is installed (for env_binding.h)")
        print("  3. Check that all C source files are present")
        return False

if __name__ == "__main__":
    success = build_extension()
    sys.exit(0 if success else 1)

