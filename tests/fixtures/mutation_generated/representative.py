from typing import Annotated, Callable, ClassVar

MutantDict = Annotated[dict[str, Callable], "Mutant"]


def _mutmut_trampoline(orig, mutants, call_args, call_kwargs, self_arg=None):
    return orig(*call_args, **call_kwargs)


def outer(value):
    def nested():
        return value

    return nested()


def x_outer__mutmut_orig(value):
    return value


def x_outer__mutmut_1(value):
    def x_nested__mutmut_99():
        return None

    return x_nested__mutmut_99()


x_outer__mutmut_mutants: ClassVar[MutantDict] = {
    "x_outer__mutmut_1": x_outer__mutmut_1,
}
x_outer__mutmut_orig.__name__ = "x_outer"


async def x_fetch__mutmut_orig(value):
    return value


async def x_fetch__mutmut_2(value):
    return None


x_fetch__mutmut_mutants: ClassVar[MutantDict] = {
    "x_fetch__mutmut_2": x_fetch__mutmut_2,
}


def x___str____mutmut_3(self):
    return "changed"


x___str____mutmut_mutants: ClassVar[MutantDict] = {
    "x___str____mutmut_3": x___str____mutmut_3,
}


class Handler:
    def xǁHandlerǁhandle__mutmut_orig(self, value):
        return value

    def xǁHandlerǁhandle__mutmut_4(self, value):
        return None

    xǁHandlerǁhandle__mutmut_mutants: ClassVar[MutantDict] = {
        "xǁHandlerǁhandle__mutmut_4": xǁHandlerǁhandle__mutmut_4,
    }


x_alias__mutmut_5 = x_outer__mutmut_1


def x_bad__mutmut_orig():
    return None


def x_bad__mutmut_zero():
    return None


def x_bad__mutmut_01():
    return None
