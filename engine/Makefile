# Veltrix 1.0 - engine Makefile (GNU Make)
# Usage:
#   make            - optimized build (x86-64-v2 baseline: SSE4.2 + POPCNT)
#   make NATIVE=1   - maximum-speed build tuned for this machine (-march=native)
#   make CXX=clang++ / make CXX=g++ / make CXX=cl (windows via build.bat instead)
#   make clean

CXX      ?= g++
TARGET   ?= veltrix
BUILDDIR ?= build

ifeq ($(OS),Windows_NT)
  EXEEXT := .exe
else
  EXEEXT :=
endif

SRCS := $(wildcard src/*.cpp)
OBJS := $(patsubst src/%.cpp,$(BUILDDIR)/%.o,$(SRCS))

BASEFLAGS := -std=c++17 -O3 -Wall -Wextra -fno-exceptions -fno-rtti -DNDEBUG -Isrc
LDFLAGS   := -lpthread

ifeq ($(NATIVE),1)
  ARCHFLAGS := -march=native
else
 ifeq ($(AVX2),1)
   ARCHFLAGS := -march=x86-64-v3
 else
   ARCHFLAGS := -march=x86-64-v2
 endif
endif

.PHONY: all clean
all: $(TARGET)$(EXEEXT)

$(BUILDDIR)/%.o: src/%.cpp
	@mkdir -p $(BUILDDIR)
	$(CXX) $(BASEFLAGS) $(ARCHFLAGS) -c $< -o $@

$(TARGET)$(EXEEXT): $(OBJS)
	$(CXX) $(OBJS) $(LDFLAGS) -o $@
	@echo Built $@ successfully.

clean:
	rm -rf $(BUILDDIR) $(TARGET)$(EXEEXT)
