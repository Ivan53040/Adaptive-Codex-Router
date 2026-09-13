# Phase 5 Qwen category review

Status: Qwen High proposal only. Every row still requires human confirmation.

## Distribution

| Category | Proposed tasks |
|---|---:|
| `simple_coding` | 18 |
| `normal_implementation` | 20 |
| `debugging` | 60 |
| `large_refactor` | 0 |
| `architecture` | 1 |
| `repository_analysis` | 0 |
| `long_agentic` | 1 |
| `large_context` | 0 |

Low-confidence proposals: 11
Missing categories: large_refactor, repository_analysis, large_context

## Review priority

These rows are low-confidence, use a rare primary category, or have weak prompt evidence.

| Task | Proposed | Secondary | Confidence | Flags |
|---|---|---|---:|---|
| pydata__xarray-6992 | `debugging` | `large_context` | 0.70 | requires_repository_inspection |
| sphinx-doc__sphinx-7590 | `normal_implementation` | — | 0.72 | requires_repository_inspection |
| sympy__sympy-12489 | `debugging` | — | 0.70 | requires_repository_inspection |
| sympy__sympy-13878 | `long_agentic` | `normal_implementation` | 0.74 | requires_repository_inspection, source_bias |
| django__django-11885 | `normal_implementation` | — | 0.71 | requires_repository_inspection |
| django__django-11740 | `debugging` | — | 0.73 | requires_repository_inspection |
| mwaskom__seaborn-3069 | `normal_implementation` | — | 0.70 | requires_repository_inspection |
| psf__requests-6028 | `debugging` | — | 0.68 | requires_repository_inspection |
| pytest-dev__pytest-5787 | `normal_implementation` | `debugging` | 0.72 | requires_repository_inspection, source_bias |
| astropy__astropy-13398 | `architecture` | `normal_implementation` | 0.65 | requires_repository_inspection, weak_prompt_evidence |
| pylint-dev__pylint-4661 | `normal_implementation` | `large_refactor` | 0.60 | requires_repository_inspection, weak_prompt_evidence |

## Confirmation checklist

| Confirm | Task | Repository | Proposed | Secondary | Confidence | Flags | Rationale |
|---|---|---|---|---|---:|---|---|
| [ ] | astropy__astropy-14369 | astropy/astropy | `debugging` | — | 0.95 | — | Bug report with repro shows CDS/MRT reader parses composite units incorrectly; dominant work is locating and fixing existing unit-parsing behavior. |
| [ ] | astropy__astropy-13453 | astropy/astropy | `debugging` | `normal_implementation` | 0.75 | source_bias | HTML writer ignores the existing formats option while other writers honor it; issue reports incorrect output, with overlap in adding missing writer support. |
| [ ] | astropy__astropy-7336 | astropy/astropy | `simple_coding` | `debugging` | 0.95 | — | Traceback shows quantity_input calls .to on None return annotation; issue suggests explicit None check, a localized decorator edit. |
| [ ] | django__django-15957 | django/django | `normal_implementation` | `debugging` | 0.80 | — | Request is to make Prefetch support sliced querysets; bounded ORM behavior extension rather than a pure one-line defect fix. |
| [ ] | django__django-13809 | django/django | `normal_implementation` | `simple_coding` | 0.90 | — | Add a --skip-checks flag to runserver, a bounded CLI feature in the existing management command framework. |
| [ ] | django__django-16100 | django/django | `normal_implementation` | `debugging` | 0.80 | — | Wrap admin changelist list_editable changes in transaction handling; bounded behavior change in an existing view, not a broad refactor. |
| [ ] | matplotlib__matplotlib-24026 | matplotlib/matplotlib | `normal_implementation` | `debugging` | 0.80 | source_bias | Change stackplot to accept color cycle references without mutating Axes cycler; bounded behavior fix with exception overlap. |
| [ ] | matplotlib__matplotlib-24570 | matplotlib/matplotlib | `simple_coding` | `debugging` | 0.90 | — | Reported reversed top/bottom alignment in HPacker with repro; likely localized correction to alignment calculation. |
| [ ] | mwaskom__seaborn-3187 | mwaskom/seaborn | `debugging` | `simple_coding` | 0.85 | — | Legend values omit ScalarFormatter offset for large ranges; requires locating and fixing formatter/legend label logic. |
| [ ] | pallets__flask-5014 | pallets/flask | `simple_coding` | `normal_implementation` | 0.90 | — | Add validation raising ValueError for empty Blueprint name; localized API guard with little investigation. |
| [ ] | psf__requests-2931 | psf/requests | `debugging` | `simple_coding` | 0.90 | — | Regression where encoded binary payload triggers to_native_string failure; requires locating and correcting request body encoding. |
| [ ] | psf__requests-1142 | psf/requests | `normal_implementation` | `debugging` | 0.75 | source_bias | Change GET request preparation to avoid automatic content-length header; bounded behavior adjustment in requests core. |
| [ ] | pydata__xarray-3993 | pydata/xarray | `normal_implementation` | `architecture` | 0.75 | — | Align DataArray.integrate parameter with Dataset.integrate, likely with deprecation; bounded public API consistency work. |
| [ ] | pydata__xarray-3677 | pydata/xarray | `debugging` | `simple_coding` | 0.90 | — | Dataset.merge fails on DataArray while top-level merge works; locate and fix coercion/merge path. |
| [ ] | pydata__xarray-4356 | pydata/xarray | `simple_coding` | `debugging` | 0.90 | — | min_count fails for multi-dim reductions; issue points to nanops shape calculation, suggesting a localized fix. |
| [ ] | pydata__xarray-6992 | pydata/xarray | `debugging` | `large_context` | 0.70 | requires_repository_inspection | Post-index-refactor invariant breaks Dataset internals; requires tracing core data model across multiple components, likely beyond one edit. |
| [ ] | pylint-dev__pylint-4551 | pylint-dev/pylint | `normal_implementation` | — | 0.85 | — | Extend pyreverse to consume PEP 484 type hints for UML attributes; bounded feature in existing UML generation. |
| [ ] | pylint-dev__pylint-7080 | pylint-dev/pylint | `debugging` | `simple_coding` | 0.90 | — | Recursive pylint ignores ignore-paths config; locate and fix file discovery/filtering logic. |
| [ ] | pylint-dev__pylint-4970 | pylint-dev/pylint | `simple_coding` | `debugging` | 0.90 | — | Make min-similarity-lines=0 disable duplicate-code check; localized configuration handling fix. |
| [ ] | pytest-dev__pytest-10356 | pytest-dev/pytest | `normal_implementation` | `debugging` | 0.80 | — | Change class marker resolution to merge marks from multiple bases by MRO; bounded behavior change in pytest collection. |
| [ ] | pytest-dev__pytest-5631 | pytest-dev/pytest | `debugging` | `simple_coding` | 0.90 | — | Regression in mock patch collection where array 'new' makes sentinel membership ambiguous; fix compatibility check. |
| [ ] | pytest-dev__pytest-7982 | pytest-dev/pytest | `simple_coding` | `debugging` | 0.95 | — | Regression where symlinked test dirs are skipped; issue points to follow_symlinks=False in collection, localized fix. |
| [ ] | scikit-learn__scikit-learn-25102 | scikit-learn/scikit-learn | `normal_implementation` | `architecture` | 0.80 | — | Add optional dtype preservation to pandas output wrapper; bounded feature spanning set_output config and transformer output path. |
| [ ] | scikit-learn__scikit-learn-25747 | scikit-learn/scikit-learn | `debugging` | `normal_implementation` | 0.80 | — | FeatureUnion with pandas output fails due to index length mismatch in output wrapper; locate and fix wrapping logic. |
| [ ] | scikit-learn__scikit-learn-13779 | scikit-learn/scikit-learn | `simple_coding` | `debugging` | 0.90 | — | Voting estimator crashes when an estimator is None and sample_weight used; add None guard in fit. |
| [ ] | sphinx-doc__sphinx-8548 | sphinx-doc/sphinx | `debugging` | `simple_coding` | 0.82 | requires_repository_inspection | Bug: inherited data-member docstring lookup misses base-class namespace; fix is localized to autodoc docstring cache search, so debugging with simple edit. |
| [ ] | sphinx-doc__sphinx-8056 | sphinx-doc/sphinx | `debugging` | `simple_coding` | 0.78 | requires_repository_inspection | Incorrect rendering of numpydoc parameters written as 'x1, x2' indicates a parsing/serialization bug in docstring parameter handling; fix is bounded. |
| [ ] | sphinx-doc__sphinx-9230 | sphinx-doc/sphinx | `debugging` | `simple_coding` | 0.84 | requires_repository_inspection | Comma inside type annotation breaks :param parsing/rendering; this is a localized docstring annotation parsing bug. |
| [ ] | sphinx-doc__sphinx-7590 | sphinx-doc/sphinx | `normal_implementation` | — | 0.72 | requires_repository_inspection | Request to add C++ user-defined literal syntax to Sphinx's C++ domain is a bounded implementation in an existing parser, not a defect fix. |
| [ ] | sympy__sympy-12489 | sympy/sympy | `debugging` | — | 0.70 | requires_repository_inspection | Permutation.__new__ hardcodes Permutation, preventing subclasses from receiving instances; fix is a defect in object construction, likely localized. |
| [ ] | sympy__sympy-13798 | sympy/sympy | `normal_implementation` | `simple_coding` | 0.76 | requires_repository_inspection | Allow arbitrary mul_symbol in latex() is a bounded API/behavior enhancement to an existing pretty-printing function, not a bug. |
| [ ] | sympy__sympy-14711 | sympy/sympy | `debugging` | `simple_coding` | 0.80 | requires_repository_inspection | Adding a zero-scaled Vector raises TypeError because _check_vector rejects non-Vector operands; fix is a localized exception handling bug. |
| [ ] | sympy__sympy-13878 | sympy/sympy | `long_agentic` | `normal_implementation` | 0.74 | requires_repository_inspection, source_bias | Adding precomputed _cdf methods and validation tests for many distributions is a multi-stage implementation with repeated formula lookup and verification. |
| [ ] | astropy__astropy-13579 | astropy/astropy | `debugging` | `large_context` | 0.75 | requires_repository_inspection | Sliced WCS world_to_pixel returns wrong pixel due to handling of coupled PCij; requires tracing WCS slicing and coordinate transformation code. |
| [ ] | astropy__astropy-8707 | astropy/astropy | `normal_implementation` | `simple_coding` | 0.77 | requires_repository_inspection | Make Header.fromstring accept Python 3 bytes/unicode is a bounded compatibility enhancement to existing FITS header parsing. |
| [ ] | astropy__astropy-14309 | astropy/astropy | `debugging` | `simple_coding` | 0.86 | — | Regression causes IndexError in identify_format when no FITS args; fix is localized to is_fits argument handling. |
| [ ] | django__django-11885 | django/django | `normal_implementation` | — | 0.71 | requires_repository_inspection | Combine fast DELETE queries by table using OR is a bounded performance/behavior implementation in Django's deletion collector, not a defect. |
| [ ] | django__django-11740 | django/django | `debugging` | — | 0.73 | requires_repository_inspection | Autodetector omits migration dependency when converting UUIDField to ForeignKey; this is a migration-generation defect requiring model graph inspection. |
| [ ] | django__django-11880 | django/django | `debugging` | `simple_coding` | 0.85 | — | Form Field __deepcopy__ shares error_messages dict across copies; fix is a localized shallow-copy defect. |
| [ ] | matplotlib__matplotlib-14623 | matplotlib/matplotlib | `debugging` | `simple_coding` | 0.80 | requires_repository_inspection | Regression: set_ylim with reversed limits fails on log scale; fix is localized to axis limit inversion logic. |
| [ ] | matplotlib__matplotlib-25332 | matplotlib/matplotlib | `debugging` | `simple_coding` | 0.81 | requires_repository_inspection | align_labels stores a weakref that blocks pickling; fix is a localized serialization bug in figure alignment state. |
| [ ] | mwaskom__seaborn-3069 | mwaskom/seaborn | `normal_implementation` | — | 0.70 | requires_repository_inspection | Make nominal scales mimic categorical axis limits, grid, and inversion is a bounded feature spanning seaborn's plotter/scale logic. |
| [ ] | psf__requests-6028 | psf/requests | `debugging` | — | 0.68 | requires_repository_inspection | Proxy requests fail with 407 on Python 3.8.12, likely due to proxy authentication header handling; requires tracing proxy auth code. |
| [ ] | psf__requests-1921 | psf/requests | `debugging` | `simple_coding` | 0.82 | — | Setting a session header to None sends literal 'None' instead of suppressing it; fix is localized header mutation logic. |
| [ ] | pydata__xarray-3095 | pydata/xarray | `debugging` | `simple_coding` | 0.78 | requires_repository_inspection | Regression in deep copy changes unicode IndexVariable dtype to object; requires tracing copy logic for coordinates/index variables. |
| [ ] | pydata__xarray-4629 | pydata/xarray | `debugging` | `simple_coding` | 0.88 | — | merge(combine_attrs='override') returns first attrs dict by reference, causing mutation aliasing; fix is a one-line copy defect. |
| [ ] | pylint-dev__pylint-8898 | pylint-dev/pylint | `debugging` | `simple_coding` | 0.83 | requires_repository_inspection | Comma-splitting in bad-names-rgxs config mangles regexes; fix is a config parsing defect in argument transformer. |
| [ ] | pylint-dev__pylint-6386 | pylint-dev/pylint | `debugging` | `simple_coding` | 0.86 | — | Short -v option incorrectly expects an argument while --verbose does not; fix is localized CLI option definition. |
| [ ] | pylint-dev__pylint-6903 | pylint-dev/pylint | `debugging` | `simple_coding` | 0.84 | — | CPU detection returns 0 in cgroup environment, crashing multiprocessing pool; fix is localized to _query_cpu fallback. |
| [ ] | pytest-dev__pytest-5787 | pytest-dev/pytest | `normal_implementation` | `debugging` | 0.72 | requires_repository_inspection, source_bias | xdist omits chained exceptions when serializing failures; implementing chain serialization is a bounded feature, though reported as a bug. |
| [ ] | pytest-dev__pytest-10051 | pytest-dev/pytest | `debugging` | `simple_coding` | 0.95 | — | Report identifies an existing state-divergence bug in caplog with a repro and pointed root cause; the fix is localized to logging fixture behavior. |
| [ ] | pytest-dev__pytest-7432 | pytest-dev/pytest | `debugging` | `simple_coding` | 0.95 | — | The issue is an incorrect skip-location reporting regression caused by --runxfail, with a repro and a likely file hint; dominant work is fixing existing behavior. |
| [ ] | scikit-learn__scikit-learn-11578 | scikit-learn/scikit-learn | `debugging` | `simple_coding` | 0.95 | — | LogisticRegressionCV scoring uses the wrong multi_class setting for the scorer model, producing inconsistent probabilities; this is a localized parameter-passing bug. |
| [ ] | scikit-learn__scikit-learn-13135 | scikit-learn/scikit-learn | `debugging` | `simple_coding` | 0.90 | — | KBinsDiscretizer raises because kmeans centers/bin_edges are unsorted before np.digitize; the task is correcting an existing edge-case failure. |
| [ ] | sphinx-doc__sphinx-9461 | sphinx-doc/sphinx | `debugging` | `normal_implementation` | 0.80 | requires_repository_inspection | Autodoc fails to document classmethod+property descriptors; the dominant issue is incorrect existing documentation behavior, likely requiring targeted descriptor handling. |
| [ ] | sphinx-doc__sphinx-9673 | sphinx-doc/sphinx | `debugging` | `normal_implementation` | 0.85 | requires_repository_inspection | A documented config option does not work with Napoleon return types; the task is fixing an incorrect interaction in existing autodoc behavior. |
| [ ] | sphinx-doc__sphinx-9711 | sphinx-doc/sphinx | `debugging` | `simple_coding` | 0.95 | — | needs_extensions compares versions lexicographically, rejecting valid newer versions; this is a localized incorrect version-comparison bug. |
| [ ] | sympy__sympy-17630 | sympy/sympy | `debugging` | `normal_implementation` | 0.85 | requires_repository_inspection | Repeated BlockMatrix multiplication raises because zero blocks become Zero instead of ZeroMatrix; the task is fixing existing block-matrix behavior. |
| [ ] | sympy__sympy-17318 | sympy/sympy | `debugging` | `simple_coding` | 0.90 | — | sqrtdenest raises IndexError on an expression that should be returned unchanged; the issue points to an unhandled case in surd splitting. |
| [ ] | sympy__sympy-15875 | sympy/sympy | `debugging` | `simple_coding` | 0.90 | — | is_zero returns an incorrect False for a complex expression; the task is fixing an incorrect predicate result in existing symbolic logic. |
| [ ] | astropy__astropy-13398 | astropy/astropy | `architecture` | `normal_implementation` | 0.65 | requires_repository_inspection, weak_prompt_evidence | Proposal redesigns ITRS-to-AltAz/HADec transform flow and obstime handling in the coordinate transform graph; structural design dominates over a small edit. |
| [ ] | astropy__astropy-7671 | astropy/astropy | `debugging` | `simple_coding` | 0.95 | — | minversion fails on dev version strings after a prior change; the issue identifies the regression and the faulty LooseVersion comparison path. |
| [ ] | astropy__astropy-14995 | astropy/astropy | `debugging` | `normal_implementation` | 0.85 | requires_repository_inspection | NDDataRef mask propagation regressed when one operand has no mask; the task is fixing incorrect arithmetic mask handling. |
| [ ] | django__django-13344 | django/django | `debugging` | `normal_implementation` | 0.80 | requires_repository_inspection | ASGI middleware receives a coroutine instead of HttpResponse; the issue is incorrect existing async response handling in the middleware chain. |
| [ ] | django__django-15731 | django/django | `debugging` | `simple_coding` | 0.95 | — | Manager methods lose signature metadata because the wrapper does not copy enough attributes; the issue even points to the likely functools.wraps fix. |
| [ ] | django__django-15315 | django/django | `debugging` | `simple_coding` | 0.90 | — | Field.__hash__ changes after assignment, breaking dict membership; the issue identifies the regression and suggests restoring immutable hash behavior. |
| [ ] | matplotlib__matplotlib-22871 | matplotlib/matplotlib | `debugging` | `normal_implementation` | 0.80 | requires_repository_inspection | ConciseDateFormatter omits the year for short date ranges when January is absent; the task is fixing existing date-formatting behavior. |
| [ ] | matplotlib__matplotlib-20676 | matplotlib/matplotlib | `debugging` | `simple_coding` | 0.85 | — | Interactive SpanSelector incorrectly expands axes limits to include zero; the issue describes a regression in existing widget behavior. |
| [ ] | psf__requests-1766 | psf/requests | `simple_coding` | `debugging` | 0.90 | — | Digest Auth qop-options must be quoted per RFC; the dominant work is a low-ambiguity formatting correction in auth header construction. |
| [ ] | pydata__xarray-6721 | pydata/xarray | `debugging` | `normal_implementation` | 0.85 | requires_repository_inspection | Accessing chunks on zarr-backed data materializes arrays unexpectedly; the task is fixing incorrect lazy-data inspection behavior. |
| [ ] | pydata__xarray-6461 | pydata/xarray | `debugging` | `simple_coding` | 0.90 | — | xr.where with a scalar second argument and keep_attrs=True raises IndexError; the issue points to a localized attrs-handling bug. |
| [ ] | pylint-dev__pylint-4661 | pylint-dev/pylint | `normal_implementation` | `large_refactor` | 0.60 | requires_repository_inspection, weak_prompt_evidence | Make pylint store data in XDG directories; likely a behavior-preserving migration touching multiple constants or modules, but scope is not fully explicit. |
| [ ] | pylint-dev__pylint-7277 | pylint-dev/pylint | `debugging` | `simple_coding` | 0.95 | — | pylint unconditionally removes the first sys.path entry; the issue identifies the line and the needed guard for runpy use. |
| [ ] | pytest-dev__pytest-6197 | pytest-dev/pytest | `debugging` | `normal_implementation` | 0.85 | requires_repository_inspection | A pytest regression causes collection to import unrelated __init__.py files; the task is fixing incorrect collection/import behavior. |
| [ ] | pytest-dev__pytest-7490 | pytest-dev/pytest | `debugging` | `normal_implementation` | 0.85 | requires_repository_inspection | Pytest 6 no longer honors dynamically added xfail markers; the issue is a regression in marker application timing or handling. |
| [ ] | pytest-dev__pytest-5809 | pytest-dev/pytest | `simple_coding` | `debugging` | 0.95 | requires_repository_inspection | Localized one-line change to use text lexer for arbitrary pytest output; no broad investigation. |
| [ ] | scikit-learn__scikit-learn-10297 | scikit-learn/scikit-learn | `normal_implementation` | `debugging` | 0.85 | source_bias | Add missing store_cv_values parameter and CV-value storage to RidgeClassifierCV, a bounded estimator feature rather than a one-line defect. |
| [ ] | scikit-learn__scikit-learn-14496 | scikit-learn/scikit-learn | `simple_coding` | `debugging` | 0.95 | — | One-line conversion of float min_samples to int before NearestNeighbors; clear exception and proposed fix. |
| [ ] | sphinx-doc__sphinx-11510 | sphinx-doc/sphinx | `debugging` | — | 0.85 | requires_repository_inspection | Incorrect source-read event handling for included files; requires tracing include/source pipeline to fix final output. |
| [ ] | sphinx-doc__sphinx-11445 | sphinx-doc/sphinx | `debugging` | — | 0.80 | requires_repository_inspection | rst_prolog incorrectly removes/domain heading from toctree; needs inspection of prolog insertion and parsing behavior. |
| [ ] | sphinx-doc__sphinx-8595 | sphinx-doc/sphinx | `simple_coding` | `debugging` | 0.85 | requires_repository_inspection | Autodoc ignores empty __all__; localized member-selection condition fix with clear expected output. |
| [ ] | sympy__sympy-13852 | sympy/sympy | `normal_implementation` | `debugging` | 0.75 | requires_repository_inspection | Implement/adjust polylog evaluation and expansion behavior; bounded mathematical feature with branch-cut considerations. |
| [ ] | sympy__sympy-18211 | sympy/sympy | `debugging` | — | 0.80 | requires_repository_inspection | solveset should return ConditionSet instead of raising; bounded behavior fix in solver fallback path. |
| [ ] | sympy__sympy-12096 | sympy/sympy | `simple_coding` | `debugging` | 0.90 | — | Function._eval_evalf must recursively evalf the _imp_ result; localized recursive call fix. |
| [ ] | astropy__astropy-7606 | astropy/astropy | `simple_coding` | `debugging` | 0.95 | — | UnrecognizedUnit.__eq__ should return False for None instead of calling Unit(None); localized exception fix. |
| [ ] | astropy__astropy-7166 | astropy/astropy | `simple_coding` | `debugging` | 0.90 | — | InheritDocstrings metaclass uses isfunction, missing properties; localized predicate fix. |
| [ ] | django__django-15128 | django/django | `debugging` | — | 0.80 | requires_repository_inspection | QuerySet OR creates alias change_map with intersecting keys/values; requires understanding query aliasing to fix assertion. |
| [ ] | django__django-16454 | django/django | `normal_implementation` | `debugging` | 0.80 | source_bias | CommandParser subparsers must inherit error-formatting arguments; bounded parser construction fix. |
| [ ] | django__django-14787 | django/django | `simple_coding` | `debugging` | 0.90 | — | method_decorator should copy wrapper assignments for partial; localized metadata preservation fix. |
| [ ] | matplotlib__matplotlib-22865 | matplotlib/matplotlib | `debugging` | — | 0.80 | requires_repository_inspection | Colorbar drawedges misses extremity edges when extend='both'; requires inspecting colorbar edge drawing logic. |
| [ ] | matplotlib__matplotlib-25122 | matplotlib/matplotlib | `simple_coding` | `debugging` | 0.95 | — | Remove unnecessary np.abs in window correction; clear formula fix with reference implementation. |
| [ ] | psf__requests-5414 | psf/requests | `simple_coding` | `debugging` | 0.90 | — | Convert IDNA/UnicodeError for empty label into InvalidUrl; localized exception-handling fix. |
| [ ] | pydata__xarray-4687 | pydata/xarray | `normal_implementation` | `debugging` | 0.80 | source_bias | xr.where should preserve attrs and dtype; bounded behavior implementation around apply_ufunc/where. |
| [ ] | pydata__xarray-4075 | pydata/xarray | `simple_coding` | `debugging` | 0.90 | — | Boolean weights cause boolean dot product; localized cast/normalization fix in weighted mean. |
| [ ] | pylint-dev__pylint-6528 | pylint-dev/pylint | `debugging` | — | 0.80 | requires_repository_inspection | Recursive mode bypasses ignore settings; requires tracing file discovery and ignore filtering to fix behavior. |
| [ ] | pytest-dev__pytest-7571 | pytest-dev/pytest | `debugging` | — | 0.85 | requires_repository_inspection | caplog regression leaves level changed; requires inspecting fixture teardown/restoration logic. |
| [ ] | pytest-dev__pytest-7521 | pytest-dev/pytest | `debugging` | — | 0.85 | requires_repository_inspection | capfd regression converts carriage returns; requires inspecting capture output normalization. |
| [ ] | scikit-learn__scikit-learn-26194 | scikit-learn/scikit-learn | `debugging` | — | 0.85 | requires_repository_inspection | roc_curve threshold construction can exceed 1 for probabilities; bounded metric logic fix. |
| [ ] | scikit-learn__scikit-learn-13142 | scikit-learn/scikit-learn | `debugging` | — | 0.85 | requires_repository_inspection | fit_predict and predict disagree for n_init>1; requires inspecting best-initialization state preservation. |
| [ ] | sphinx-doc__sphinx-9229 | sphinx-doc/sphinx | `debugging` | — | 0.80 | requires_repository_inspection | Autodoc inconsistently discards type-alias docstrings; requires inspecting alias docstring handling. |

Do not promote these labels into the benchmark manifest until the checklist has been reviewed.
