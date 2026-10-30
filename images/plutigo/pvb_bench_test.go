// plutus-vm-benchmark harness for plutigo, added to the pinned repo's tests package
// (images/plutigo/Dockerfile). docs/IMAGE_CONTRACT.md, spec D3/D4/D11.
//
// Parameters (check/README.md, "Evaluation parameters"): PlutusV3 for every program (not the
// language taken from the program version), protocol version 11, the mainnet PlutusV3 cost model
// through cek.NewEvalContext, counting mode (no budget limit).
//
//	BenchmarkPvbFlatFiles  flat decode + eval per iteration. A script that fails its first
//	                       evaluation prints "EVAL_FAIL: <name>" and is not timed.
//	BenchmarkPvbEval       eval only: the program is decoded once before timing, each iteration
//	                       runs it on the reused machine (plutigo-eval.csv, see below).
//	TestPvbCheck           one evaluation per script, writes $PVB_CHECK_OUT
//	                       (vm,script,status,cpu,mem)
//
// scripts/run-plutigo.sh runs both benchmarks in one process per script; Go runs them in source
// order, BenchmarkPvbFlatFiles first. Each prints "PVB_LOOP <d3|eval> <name>" before its timing of
// a script starts (parsers/fill_failures.py --loop).
//
// Environment: PVB_DATA_DIR (the .flat files), PVB_COSTMODEL (the mainnet array, one integer per
// line), PVB_CHECK_OUT.
package tests

import (
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"

	"github.com/blinklabs-io/plutigo/cek"
	"github.com/blinklabs-io/plutigo/lang"
	"github.com/blinklabs-io/plutigo/syn"
)

// Counting mode: a budget too large to run out.
var pvbBudget = cek.ExBudget{Mem: math.MaxInt64, Cpu: math.MaxInt64}

type pvbScript struct {
	name    string
	content []byte
}

func pvbScripts(tb testing.TB) []pvbScript {
	dir := os.Getenv("PVB_DATA_DIR")
	if dir == "" {
		tb.Fatal("set PVB_DATA_DIR")
	}
	paths, err := filepath.Glob(filepath.Join(dir, "*.flat"))
	if err != nil || len(paths) == 0 {
		tb.Fatalf("no .flat files in %s (%v)", dir, err)
	}
	sort.Strings(paths)
	scripts := make([]pvbScript, 0, len(paths))
	for _, p := range paths {
		content, err := os.ReadFile(p)
		if err != nil {
			tb.Fatal(err)
		}
		scripts = append(scripts, pvbScript{strings.TrimSuffix(filepath.Base(p), ".flat"), content})
	}
	return scripts
}

func pvbEvalContext(tb testing.TB) *cek.EvalContext {
	path := os.Getenv("PVB_COSTMODEL")
	raw, err := os.ReadFile(path)
	if err != nil {
		tb.Fatalf("PVB_COSTMODEL: %v", err)
	}
	var params []int64
	for _, f := range strings.Fields(string(raw)) {
		v, err := strconv.ParseInt(f, 10, 64)
		if err != nil {
			tb.Fatal(err)
		}
		params = append(params, v)
	}
	if len(params) != 350 {
		tb.Fatalf("%s: expected the 350 PlutusV3 parameters, got %d", path, len(params))
	}
	ctx, err := cek.NewEvalContext(lang.LanguageVersionV3, cek.ProtoVersion{Major: 11}, params)
	if err != nil {
		tb.Fatalf("NewEvalContext: %v", err)
	}
	return ctx
}

func pvbMachine(ctx *cek.EvalContext) *cek.Machine[syn.DeBruijn] {
	m := cek.NewMachine[syn.DeBruijn](lang.LanguageVersionV3, 0, ctx)
	m.ExBudget = pvbBudget
	return m
}

// pvbEvalOnce decodes and evaluates on a fresh machine: (cpu, mem, error).
func pvbEvalOnce(ctx *cek.EvalContext, content []byte) (int64, int64, error) {
	program, err := syn.Decode[syn.DeBruijn](content)
	if err != nil {
		return 0, 0, fmt.Errorf("decode: %w", err)
	}
	m := pvbMachine(ctx)
	_, err = m.Run(program.Term)
	return pvbBudget.Cpu - m.ExBudget.Cpu, pvbBudget.Mem - m.ExBudget.Mem, err
}

func TestPvbCheck(t *testing.T) {
	out := os.Getenv("PVB_CHECK_OUT")
	if out == "" {
		t.Skip("PVB_CHECK_OUT not set")
	}
	ctx := pvbEvalContext(t)
	var sb strings.Builder
	sb.WriteString("vm,script,status,cpu,mem\n")
	for _, s := range pvbScripts(t) {
		cpu, mem, err := pvbEvalOnce(ctx, s.content)
		status := "ok"
		if err != nil {
			status = "error"
			fmt.Printf("CHECK_FAIL: %s: %.200s\n", s.name, err.Error())
		}
		fmt.Fprintf(&sb, "plutigo,%s,%s,%d,%d\n", s.name, status, cpu, mem)
	}
	if err := os.WriteFile(out, []byte(sb.String()), 0o644); err != nil {
		t.Fatal(err)
	}
}

func BenchmarkPvbFlatFiles(b *testing.B) {
	ctx := pvbEvalContext(b)
	for _, s := range pvbScripts(b) {
		if _, _, err := pvbEvalOnce(ctx, s.content); err != nil {
			fmt.Printf("EVAL_FAIL: %s\n  %.200s\n", s.name, err.Error())
			continue
		}
		content := s.content
		fmt.Printf("PVB_LOOP d3 %s\n", s.name)
		b.Run(s.name, func(b *testing.B) {
			// One machine per script; Run restores the initial budget on every call.
			machine := pvbMachine(ctx)
			decoder := syn.NewDeBruijnDecoder()
			for b.Loop() {
				program, err := decoder.DecodeBorrowed(content)
				if err != nil {
					b.Fatalf("decode error: %v", err)
				}
				if _, err := machine.Run(program.Term); err != nil {
					b.Fatalf("eval error: %v", err)
				}
			}
		})
	}
}

// BenchmarkPvbEval times evaluation only: the program is decoded once, outside the timed loop.
//
// The machine is built once per script, as in BenchmarkPvbFlatFiles. Machine.Run at the pinned
// SHA gives every call fresh evaluation state (cek/machine.go, Run): it restores the initial
// budget when the caller did not change it (lines 939-942), empties Logs and the unbudgeted step
// counters (950-952), resets the frame stack (944, 957), and its deferred block clears the value
// and env arenas (953-971); the environment of a run starts empty (stack_machine_debruijn.go 265).
// What survives a run is allocator state: object pools, arena chunks and an interning cache of
// immutable integer constants (cek/value.go 98-113).
//
// Before timing, the prelude checks this: two runs on the reused machine must consume the same
// budget as a run on a fresh machine. A mismatch prints "EVAL_FAIL: <name>" and the script is not
// timed.
func BenchmarkPvbEval(b *testing.B) {
	ctx := pvbEvalContext(b)
	for _, s := range pvbScripts(b) {
		fmt.Printf("PVB_LOOP eval %s\n", s.name)
		cpu, mem, err := pvbEvalOnce(ctx, s.content)
		if err != nil {
			fmt.Printf("EVAL_FAIL: %s\n  %.200s\n", s.name, err.Error())
			continue
		}
		program, err := syn.Decode[syn.DeBruijn](s.content)
		if err != nil {
			fmt.Printf("EVAL_FAIL: %s\n  decode: %.200s\n", s.name, err.Error())
			continue
		}
		machine := pvbMachine(ctx)
		reuseOk := true
		for range 2 {
			if _, err := machine.Run(program.Term); err != nil {
				reuseOk = false
				break
			}
			if pvbBudget.Cpu-machine.ExBudget.Cpu != cpu || pvbBudget.Mem-machine.ExBudget.Mem != mem {
				reuseOk = false
				break
			}
		}
		if !reuseOk {
			fmt.Printf("EVAL_FAIL: %s\n  a reused machine does not reproduce the budget of a fresh one\n", s.name)
			continue
		}
		b.Run(s.name, func(b *testing.B) {
			machine := pvbMachine(ctx)
			term := program.Term
			for b.Loop() {
				if _, err := machine.Run(term); err != nil {
					b.Fatalf("eval error: %v", err)
				}
			}
		})
	}
}
