CXX ?= c++
CXXFLAGS ?= -O3 -std=c++17 -Wall -Wextra -Wpedantic
SOURCE_SHA256 := $(shell python3 -c 'import hashlib; print(hashlib.sha256(open("gumbel_topk.cpp","rb").read()).hexdigest())')
DEFINES = -DGTOPK_SOURCE_SHA256=\"$(SOURCE_SHA256)\"

ifeq ($(shell uname -s),Darwin)
LIBOMP_PREFIX ?= $(shell brew --prefix libomp 2>/dev/null)
OMP_FLAGS = -Xpreprocessor -fopenmp -I$(LIBOMP_PREFIX)/include
OMP_LIBS = -L$(LIBOMP_PREFIX)/lib -Wl,-rpath,$(LIBOMP_PREFIX)/lib -lomp
else
OMP_FLAGS = -fopenmp
OMP_LIBS = -fopenmp
endif

.PHONY: all serial clean
all: build/gumbel_topk
serial: build/gumbel_topk_serial

build/gumbel_topk: gumbel_topk.cpp Makefile
	mkdir -p build
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(DEFINES) $(OMP_FLAGS) $< -o $@ $(LDFLAGS) $(OMP_LIBS)

build/gumbel_topk_serial: gumbel_topk.cpp Makefile
	mkdir -p build
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(DEFINES) $< -o $@ $(LDFLAGS)

clean:
	rm -rf build
