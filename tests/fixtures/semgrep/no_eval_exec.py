# negative: no eval/exec, just normal code
import ast

ast.literal_eval("(1, 2)")
