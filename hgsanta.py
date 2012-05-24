# -*- coding: utf8 -*-
import re
import envoy

import argparse


def print_hunk(patch, line):
    in_hunk = False
    minwidth = -1
    for l in patch.split('\n'):
        # todo make this work with the rest of the diff format:
        # http://www.gnu.org/software/diffutils/manual/html_node/Detailed-Unified.html#Detailed-Unified
        m = re.match(r"^@@ -(\d+),(\d+) \+(\d+),(\d+) @@$", l)
        if m:
            if in_hunk:
                in_hunk = False

            lines_from = (int(m.group(1)), int(m.group(2)))
            lines_to = (int(m.group(3)), int(m.group(4)))

            if line >= lines_to[0] and line <= lines_to[0] + lines_to[1]:
                in_hunk = True
                minwidth = len(str(max(lines_to[0], lines_to[0] + lines_to[1])))
                print l
                line_no = lines_from[0]
        elif in_hunk and l:
            if l[0] == '+':
                print minwidth * ' ',
            if l[0] != '+':
                fmt = '%' + str(minwidth) + 'i'
                print fmt % line_no,
                line_no += 1
            print l


def santa(rev, line, context, filename):

    original_rev = None
    original_line = None

    cmd = "hg blame -ln %s -r %s" % (filename, rev)
    print cmd
    result = envoy.run(cmd).std_out.split('\n')

    # print result[line - 1]
    m = re.match(r"^\s*(\d+):\s+(\d+):.*$", result[line - 1])
    original_rev, original_line = m.group(1), int(m.group(2))

    if context > 0:
        line_s = line - 1 - context
        line_e = line - 1 + context + 1
        display = result[line_s:line_e]

        print "lines %i±%i:" % (line, context)

        for l in display:
            print l

        print

    rev = original_rev
    line = original_line

    cmd = "hg log -r %s -f %s -p" % (rev, filename)
    print cmd

    # print the summary
    print envoy.run("hg log -r %s -f %s" % (rev, filename)).std_out

    r = envoy.run(cmd)
    patch = r.std_out

    print_hunk(patch, line)

    cmd = "hg parent -r %s" % rev
    parent = envoy.run(cmd).std_out.split('\n')[0]
    m = re.match("^changeset:\s+(\d+):(\w+)$", parent)
    parent = int(m.group(1))

    print "parent is %s" % parent
    rev = parent
    line = raw_input("Enter line number for next iteration, or hit enter to exit: ")
    if line:
        line = int(line)
        print
        print

        # recurse until we overflow the stack or run out of history :)
        santa(rev, line, context, filename)


def main():
    parser = argparse.ArgumentParser(description='omniscient blame')
    parser.add_argument('line', type=int, help='line number to trace')
    parser.add_argument('file', type=str, help='file to trace')
    parser.add_argument('--rev', default='tip', type=str, help='revision to start from')
    parser.add_argument('--context', default=0, type=int)
    args = parser.parse_args()

    santa(args.rev, args.line, args.context, args.file)

if __name__ == "__main__":
    main()
