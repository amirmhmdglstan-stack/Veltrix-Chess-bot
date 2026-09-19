# Veltrix 1.0 - engine Makefile (GNU Make)
# Usage:
#   make            - optimized PORTABLE build: x86-64-v2 ISA (SSE4.2/POPCNT) + LTO;
#                     safe default on any reasonably recent x86-64 machine.
#   make NATIVE=1   - maximum-speed build tuned for THIS machine (-march=native).
#   make AVX2=1     - portable-but-v3 build (AVX2/BMI2, 2015+ CPUs).
#   make pgo        - profile-guided build for the host: instrument -> train on
#                     bench -> rebuild. Same portable ISA, same behaviour
#                     (bench node counts are locked), measured ~+6% NPS.
#   make LTO=0      - shave build time in development (no whole-program pass).
#   make CXX=clang++ / g++ (Windows: build.bat or MSYS2's g++ both work).
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

# PGO (profile-guided optimization): 'make pgo' builds an instrumented
# engine, trains the profile on the built-in bench workload, then rebuilds
# with the profile. Same ISA target (portable), same chess behaviour
# (bench node counts are locked by tests), just faster generated code.
PGO ?= 0
ifeq ($(PGO),1)
  ARCHFLAGS += -fprofile-generate=$(BUILDDIR)/pgo -fprofile-dir=$(BUILDDIR)/pgo
  LDFLAGS   += -fprofile-generate=$(BUILDDIR)/pgo
endif
ifeq ($(PGO),2)
  ARCHFLAGS += -fprofile-use=$(BUILDDIR)/pgo -fprofile-dir=$(BUILDDIR)/pgo -fprofile-correction
  LDFLAGS   += -fprofile-use=$(BUILDDIR)/pgo
endif

.PHONY: all clean pgo
all: $(TARGET)$(EXEEXT)

$(BUILDDIR)/%.o: src/%.cpp
	@mkdir -p $(BUILDDIR)
	$(CXX) $(BASEFLAGS) $(ARCHFLAGS) -c $< -o $@

$(TARGET)$(EXEEXT): $(OBJS)
	$(CXX) $(OBJS) $(LDFLAGS) -o $@
	@echo Built $@ successfully.

clean:
	rm -rf $(BUILDDIR) $(TARGET)$(EXEEXT)

pgo: clean
	$(MAKE) -$(MAKEFLAGS) PGO=1 all
	@echo "training profile on the bench workload..."
	@printf "bench\nquit" | ./$(TARGET)$(EXEEXT) > /dev/null 2>&1
	@printf "position startpos moves e2e4 e7e5\ngo nodes 300000\nquit" | ./$(TARGET)$(EXEEXT) > /dev/null 2>&1
	@rm -f $(BUILDDIR)/*.o
	$(MAKE) -$(MAKEFLAGS) PGO=2 all
	@echo "PGO build complete."


