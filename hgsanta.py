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

    m = re.match(r"^\s*(\d+):\s*(\d+):.*$", result[line - 1])
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

    # todo this can be pretty horrible when the hunk is large.
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
    parser.add_argument('--rev', default='tip', type=str, help='revision to start from')
    parser.add_argument('--context', default=0, type=int)
    args = parser.parse_args()

    santa(args.rev, args.line, args.context, args.file)


import mercurial.extensions
import mercurial.commands

from mercurial.node import hex, short
from mercurial import scmutil, patch, util, encoding


def _(s):
    return s


def real_annotate(ui, repo, *pats, **opts):
    """show changeset information by line for each file

    List changes in files, showing the revision id responsible for
    each line

    This command is useful for discovering when a change was made and
    by whom.

    Without the -a/--text option, annotate will avoid processing files
    it detects as binary. With -a, annotate will annotate the file
    anyway, although the results will probably be neither useful
    nor desirable.

    Returns 0 on success.
    """
    if opts.get('follow'):
        # --follow is deprecated and now just an alias for -f/--file
        # to mimic the behavior of Mercurial before version 1.5
        opts['file'] = True

    datefunc = ui.quiet and util.shortdate or util.datestr
    getdate = util.cachefunc(lambda x: datefunc(x[0].date()))

    if not pats:
        raise util.Abort(_('at least one filename or pattern is required'))

    hexfn = ui.debugflag and hex or short

    opmap = [('user', ' ', lambda x: ui.shortuser(x[0].user())),
             ('number', ' ', lambda x: str(x[0].rev())),
             ('changeset', ' ', lambda x: hexfn(x[0].node())),
             ('date', ' ', getdate),
             ('file', ' ', lambda x: x[0].path()),
             ('line_number', ':', lambda x: str(x[1])),
            ]

    if (not opts.get('user') and not opts.get('changeset')
        and not opts.get('date') and not opts.get('file')):
        opts['number'] = True

    linenumber = opts.get('line_number') is not None
    if linenumber and (not opts.get('changeset')) and (not opts.get('number')):
        raise util.Abort(_('at least one of -n/-c is required for -l'))

    funcmap = [(func, sep) for op, sep, func in opmap if opts.get(op)]
    funcmap[0] = (funcmap[0][0], '')  # no separator in front of first column

    def bad(x, y):
        raise util.Abort("%s: %s" % (x, y))

    ctx = scmutil.revsingle(repo, opts.get('rev'))
    m = scmutil.match(ctx, pats, opts)
    m.bad = bad
    follow = not opts.get('no_follow')
    diffopts = patch.diffopts(ui, opts, section='annotate')
    for abs in ctx.walk(m):
        fctx = ctx[abs]

        if not opts.get('text') and util.binary(fctx.data()):
            ui.write(_("%s: binary file\n") % ((pats and m.rel(abs)) or abs))
            continue

        lines = fctx.annotate(follow=follow, linenumber=linenumber,
                              diffopts=diffopts)
        pieces = []

        for f, sep in funcmap:
            l = [f(n) for n, dummy in lines]
            if l:
                sized = [(x, encoding.colwidth(x)) for x in l]
                ml = max([w for x, w in sized])
                pieces.append(["%s%s%s" % (sep, ' ' * (ml - w), x)
                               for x, w in sized])

        if pieces:
            for p, l in zip(zip(*pieces), lines):
                ui.write("%s: %s" % ("".join(p), l[1]))

            if lines and not lines[-1][1].endswith('\n'):
                ui.write('\n')


def blame_trail(origfn, ui, repo, *pats, **opts):
    trail_line = opts['trail']
    if trail_line == -1:
        return origfn(ui, repo, *pats, **opts)

    # have to use line_number for trail
    opts['line_number'] = True

    if opts.get('follow'):
        # --follow is deprecated and now just an alias for -f/--file
        # to mimic the behavior of Mercurial before version 1.5
        opts['file'] = True

    datefunc = ui.quiet and util.shortdate or util.datestr
    getdate = util.cachefunc(lambda x: datefunc(x[0].date()))

    if not pats:
        raise util.Abort(_('at least one filename or pattern is required'))

    hexfn = ui.debugflag and hex or short

    opmap = [('user', ' ', lambda x: ui.shortuser(x[0].user())),
             ('number', ' ', lambda x: str(x[0].rev())),
             ('changeset', ' ', lambda x: hexfn(x[0].node())),
             ('date', ' ', getdate),
             ('file', ' ', lambda x: x[0].path()),
             ('line_number', ':', lambda x: str(x[1])),
            ]

    if (not opts.get('user') and not opts.get('changeset')
        and not opts.get('date') and not opts.get('file')):
        opts['number'] = True

    linenumber = opts.get('line_number') is not None
    if linenumber and (not opts.get('changeset')) and (not opts.get('number')):
        raise util.Abort(_('at least one of -n/-c is required for -l'))

    funcmap = [(func, sep) for op, sep, func in opmap if opts.get(op)]
    funcmap[0] = (funcmap[0][0], '')  # no separator in front of first column

    def bad(x, y):
        raise util.Abort("%s: %s" % (x, y))

    ctx = scmutil.revsingle(repo, opts.get('rev'))
    m = scmutil.match(ctx, pats, opts)
    m.bad = bad
    follow = not opts.get('no_follow')
    diffopts = patch.diffopts(ui, opts, section='annotate')

    files = list(ctx.walk(m))
    assert len(files) == 1
    # todo what fails this assertion? original code assumed more than one file.

    fctx = ctx[files[0]]

    if not opts.get('text') and util.binary(fctx.data()):
        ui.write(_("%s: binary file\n") % ((pats and m.rel(abs)) or abs))
        return

    lines = fctx.annotate(follow=follow, linenumber=linenumber,
                          diffopts=diffopts)

    metadata, line_contents = lines[trail_line - 1]
    original_rev = metadata[0].rev()
    original_line = metadata[1]

    context = opts['context']
    if context != -1:
        line_s = trail_line - 1 - context
        line_e = trail_line - 1 + context + 1
        display_lines = lines[line_s:line_e]

        print "lines %i±%i:" % (trail_line, context)

        for l in display_lines:
            print "%s: %s: %s" % (l[0][0].rev(), l[0][1], l[1]),

        print

    rev = original_rev
    line = original_line

    # print the summary of the diff
    mercurial.commands.log(ui, repo, *pats, rev=[rev], follow=True, date=None)

    # now look at just the hunk with this line
    show_hunk(ui, repo, *pats, patch=True, rev=[rev], follow=True, date=None)

    # cmd = "hg parent -r %s" % rev
    # parent = envoy.run(cmd).std_out.split('\n')[0]
    # m = re.match("^changeset:\s+(\d+):(\w+)$", parent)
    # parent = int(m.group(1))

    # print "parent is %s" % parent
    # rev = parent
    # line = raw_input("Enter line number for next iteration, or hit enter to exit: ")
    # if line:
    #     line = int(line)
    #     print
    #     print

    #     # recurse until we overflow the stack or run out of history :)
    #     santa(rev, line, context, filename)


from mercurial import cmdutil, templatekw, nullrev


def show_hunk(ui, repo, *pats, **opts):
    matchfn = scmutil.match(repo[None], pats, opts)
    limit = cmdutil.loglimit(opts)
    count = 0

    getrenamed, endrev = None, None
    # if opts.get('copies'):
    #     if opts.get('rev'):
    #         endrev = max(scmutil.revrange(repo, opts.get('rev'))) + 1
    #     getrenamed = templatekw.getrenamedfn(repo, endrev=endrev)

    df = False
    # if opts["date"]:
    #     df = util.matchdate(opts["date"])

    branches = opts.get('branch', []) + opts.get('only_branch', [])
    opts['branch'] = [repo.lookupbranch(b) for b in branches]

    displayer = cmdutil.show_changeset(ui, repo, opts, True)

    def prep(ctx, fns):
        rev = ctx.rev()
        parents = [p for p in repo.changelog.parentrevs(rev)
                   if p != nullrev]
        if opts.get('no_merges') and len(parents) == 2:
            return
        if opts.get('only_merges') and len(parents) != 2:
            return
        if opts.get('branch') and ctx.branch() not in opts['branch']:
            return
        if not opts.get('hidden') and ctx.hidden():
            return
        if df and not df(ctx.date()[0]):
            return

        lower = encoding.lower
        if opts.get('user'):
            luser = lower(ctx.user())
            for k in [lower(x) for x in opts['user']]:
                if (k in luser):
                    break
            else:
                return
        if opts.get('keyword'):
            luser = lower(ctx.user())
            ldesc = lower(ctx.description())
            lfiles = lower(" ".join(ctx.files()))
            for k in [lower(x) for x in opts['keyword']]:
                if (k in luser or k in ldesc or k in lfiles):
                    break
            else:
                return

        copies = None
        if getrenamed is not None and rev:
            copies = []
            for fn in ctx.files():
                rename = getrenamed(fn, rev)
                if rename:
                    copies.append((fn, rename[0]))

        revmatchfn = None
        if opts.get('patch') or opts.get('stat'):
            if opts.get('follow') or opts.get('follow_first'):
                # note: this might be wrong when following through merges
                revmatchfn = scmutil.match(repo[None], fns, default='path')
            else:
                revmatchfn = matchfn

        displayer.show(ctx, copies=copies, matchfn=revmatchfn)

    for ctx in cmdutil.walkchangerevs(repo, matchfn, opts, prep):
        if count == limit:
            break
        if displayer.flush(ctx.rev()):
            count += 1
    displayer.close()

def uisetup(ui):
    entry = mercurial.extensions.wrapcommand(mercurial.commands.table, 'annotate',
        blame_trail)
    extra_opts = [
        ('t', 'trail', -1, ("know who's been naughty or nice")),
        ('c', 'context', 0, ("how much context to show around hunks"))
    ]
    entry[1].extend(extra_opts)
