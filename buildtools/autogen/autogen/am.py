# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.  If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright 1997 - July 2008 CWI, August 2008 - 2016 MonetDB B.V.

import os
import posixpath
import sys
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from codegen import find_org
import re

automake_ext = ['', 'c', 'def', 'h', 'lo', 'o', 'pm.c',
                'tab.c', 'tab.h', 'yy.c']

# buildtools_ext contains the extensions of files from which sources
# are generated by rules that are specified in rules.mk in
# buildtools/conf.  The generated sources should therefore be included
# in the tar ball and not be removed with `make distclean' when
# running "in" said tar ball.
buildtools_ext = ['brg', 'l', 'pm.i', 'syms', 't', 'y']

am_assign = "+="

def split_filename(f):
    base = f
    ext = ""
    if f.find(".") >= 0:
        return f.split(".", 1)
    return base, ext

def rsplit_filename(f):
    base = f
    ext = ""
    s = f.rfind(".")
    if s >= 0:
        return f[:s], f[s+1:]
    return base, ext

def cond_subdir(fd, dir, i):
    res = ""
    parts = dir.split("?")
    if len(parts) == 2:
        dirs = parts[1].split(":")
        fd.write("if %s\n" % parts[0])
        if len(dirs) > 0 and dirs[0].strip() != "":
            fd.write("%s_%d_SUBDIR = %s\n" % (parts[0], i, dirs[0]))
        else:
            fd.write("%s_%d_SUBDIR = \n" % (parts[0], i))
        if len(dirs) > 1 and dirs[1].strip() != "":
            fd.write("else\n")
            fd.write("%s_%d_SUBDIR = %s\n" % (parts[0], i, dirs[1]))
        else:
            fd.write("else\n")
            fd.write("%s_%d_SUBDIR = \n" % (parts[0], i))
        fd.write("endif\n")
        res = "$(" + parts[0] + "_" + str(i) + "_SUBDIR)"
    return res

def am_sort_libs(libs, tree):
    res = []
    for (pref,lib,sep,cond) in libs:
        after = -1
        # does lib depend on another library
        if 'lib_'+ lib in tree:
            v = tree['lib_'+lib]
            if "LIBS" in v:
                for l in v['LIBS']:
                    if len(l) > 3:
                        l = l[3:] # strip lib prefix
                    if l in res:
                        pos = res.index(l)
                        if pos > after:
                            after = pos
        elif 'LIBS' in tree:
            v = tree['LIBS']
            if lib[1:] + "_DLIBS" in v:
                for l in v[lib[1:] + '_DLIBS']:
                    if len(l) > 3:
                        l = l[3:] # strip lib prefix
                    if l in res:
                        pos = res.index(l)
                        if pos > after:
                            after = pos
        res.insert(after + 1, (pref, lib, sep, cond))
    return res

def am_subdirs(fd, var, values, am):
    dirs = []
    i = 0
    for dir in values:
        i = i + 1
        if dir.find("?") > -1:
            dirs.append(cond_subdir(fd, dir, i))
        else:
            dirs.append(dir)

    am_assignment(fd, var, dirs, am)

def am_assignment(fd, var, values, am):
    o = ""
    for v in values:
        o = o + " " + am_translate_dir(v, am)
    fd.write("%s = %s\n" % (var, o))

def am_cflags(fd, var, values, am):
    o = ""
    for v in values:
        o = o + " " + v
    fd.write("%s %s %s\n" % (var, am_assign, o))

def am_extra_dist(fd, var, values, am):
    for i in values:
        am['EXTRA_DIST'].append(i)
        t, ext = rsplit_filename(i)
        if ext == 'in':
            am['OutList'].append(am['CWD']+t)

def am_extra_dist_dir(fd, var, values, am):
    fd.write("dist-hook:\n")
    for i in values:
        fd.write("\tmkdir -p $(distdir)/%s\n" % i)
        fd.write("\tcp -pR $(srcdir)/%s/* $(distdir)/%s\n" % (i, i))

def am_extra_headers(fd, var, values, am):
    for i in values:
        am['HDRS'].append(i)

def am_libdir(fd, var, values, am):
    am['LIBDIR'] = values[0]

def am_mtsafe(fd, var, values, am):
    fd.write("CFLAGS %s $(THREAD_SAVE_FLAGS)\n" % am_assign)

def am_list2string(l, pre, post):
    res = ""
    prev = None
    for i in sorted(l):
        if i == prev:
            continue
        res = res + pre + i + post
        prev = i
    return res

def am_find_srcs(target, deps, am, cond):
    dist = 0
    base, ext = split_filename(target)
    f = target
    pf = f
    while ext != "h" and f in deps:
        f = deps[f][0]
        b, ext = split_filename(f)
        if ext in automake_ext:
            pf = f

    # built source if has dep and ext != cur ext
    if not(cond) and pf in deps and pf not in am['BUILT_SOURCES']:
        pfb, pfext = split_filename(pf)
        sfb, sfext = split_filename(deps[pf][0])
        if sfext != pfext:
            if pfext in automake_ext:
                dist = None
                am['BUILT_SOURCES'].append(pf)
                am['CLEAN'].append(pf)
    b, ext = split_filename(pf)
    if ext in automake_ext:
        return dist, pf
    return dist, ""

def am_find_hdrs_r(am, target, deps, hdrs, hdrs_ext, map):
    if target in deps:
        tdeps = deps[target]
        for dtarget in tdeps:
            t, ext = split_filename(dtarget)
            org = find_org(deps, dtarget)
            if org in map['SOURCES']:
                if ext in hdrs_ext and dtarget not in hdrs and '/' not in dtarget:
                    hdrs.append(dtarget)
                am_find_hdrs_r(am, dtarget, deps, hdrs, hdrs_ext, map)

def am_find_hdrs(am, map):
    if 'HEADERS' in map:
        hdrs_ext = map['HEADERS']
        for target in map['TARGETS']:
            t, ext = split_filename(target)
            if ext in hdrs_ext and not target in am['HDRS']:
                am['HDRS'].append(target)
            am_find_hdrs_r(am, target, map['DEPS'], am['HDRS'], hdrs_ext, map)

def am_find_ins(am, map):
    for source in map['SOURCES']:
        t, ext = rsplit_filename(source)
        if ext == 'in':
            am['OutList'].append(am['CWD']+t)

def am_additional_flags(name, sep, type, list, am, pref = 'lib'):
    if type == "BIN":
        add = am_normalize(name)+"_LDFLAGS ="
    elif type == "LIB":
        add = pref+sep+name+"_la_LDFLAGS ="
    else:
        add = name + " ="
    for l in list:
        add = add + " " + l
    return add + "\n"

libno = 0
def am_additional_libs(name, sep, type, list, am, pref = 'lib'):
    if type == "BIN":
        add = am_normalize(name)+"_LDADD ="
    elif type == "LIB":
        add = pref+sep+name+"_la_LIBADD ="
    else:
        add = name + " ="
    for l in list:
##        if 'lib_' in l or l.startswith('-l_'):
##            continue
        if '?' in l:
            c, l = l.split('?', 1)
        else:
            c = None
        if l[0] not in ("-", "$", "@"):
            l = am_translate_dir(l, am) + ".la"
        if c:
            global libno
            v = 'LIB%d' % libno
            libno = libno + 1
            add = 'if %s\n%s = %s\nelse\n%s =\nendif\n%s' % (c, v, l, v, add)
            l = '$(%s)' % v
        add = add + " " + l
    return add + "\n"

def am_additional_deps(name, sep, type, list, am, pref = 'lib'):
    if type == "BIN":
        add = am_normalize(name)+"_DEPENDENCIES ="
    elif type == "LIB":
        add = pref+sep+name+"_la_DEPENDENCIES ="
    else:
        add = name + " ="
    for l in list:
        add = add + " " + l
    return add + "\n"

def am_additional_install_libs(name, sep, list, am):
    add = "$(do)install-" + name + "LTLIBRARIES : "
    for l in list:
        if '?' in l:
            c, l = l.split('?', 1)
        else:
            c = None
        if l[0] not in ("-", "$", "@", "." ):
            if l[3] == '_':
                l = l[4:]
            else:
                l = l[3:]
            l = 'install-%sLTLIBRARIES' % l
            if c:
                global libno
                v = 'LIB%d' % libno
                libno = libno + 1
                add = 'if %s\n%s = %s\nelse\n%s =\nendif\n%s' % (c, v, l, v, add)
                l = '$(%s)' % v
            add = add + " " + l
    return add + "\n"

def needbuildtool(deplist):
    for d in deplist:
        f,ext = rsplit_filename(d)
        if ext in buildtools_ext:
            return 1
    return 0

def am_dep(fd, t, deplist, am, pref = ''):
    rv = []
    t = t.replace('\\', '/')
    n = t.replace('.o', '.lo', 1)
    f,ext = rsplit_filename(n)
    if t != n and not pref:
        fd.write(t + " ")
        rv.append(t)
    fd.write(pref + n + ":")
    rv.append(pref + n)
    for d in deplist:
        if not posixpath.isabs(d):
            fd.write(" " + am_translate_dir(d, am))
        else:
            print("!WARNING: dropped absolute dependency " + d)
    fd.write("\n")
    return rv

def am_deps(fd, deps, am):
    if not am['DEPS']:
        for t, deplist in deps.items():
            rv = am_dep(fd, t, deplist, am)
            if needbuildtool(deplist):
                am['CLEAN'].extend(rv)
    am['DEPS'].append("DONE")

# list of scripts to install
def am_scripts(fd, var, scripts, am):
#todo handle 'EXT' for empty ''.

    s, ext = var.split('_', 1)
    ext = [ ext ]
    if "EXT" in scripts:
        ext = scripts["EXT"] # list of extentions

    sd = "bindir"
    if "DIR" in scripts:
        sd = scripts["DIR"][0] # use first name given
    sd = am_translate_dir(sd, am)

    for src in scripts['SOURCES']:
        am['EXTRA_DIST'].append(src)

    for script in scripts['TARGETS']:
        s,ext2 = rsplit_filename(script)
        if not ext2 in ext:
            continue

        cond = ''
        s = script
        scriptname = "script_" + script
        if 'COND' in scripts:
            condname = '+'.join(scripts['COND'])
            mkname = am_normalize(script.replace('.', '_'))
            cond = '#' + condname
            s = "$(C_" + mkname + ")"
            scriptname = "$(C_script_" + mkname + ")"

        name = "script_" + script
        if scriptname not in am['BIN_SCRIPTS'] and name not in am['BIN_SCRIPTS']:
            am['BIN_SCRIPTS'].append(scriptname)
        else:
            continue

        if cond:
            fd.write("uninstall-local-:\n")
            fd.write("install-exec-local-:\n")
            for condname in scripts['COND']:
                fd.write("if %s\n" % condname)
            fd.write(" C_%s = %s\n" % (mkname,script))
            fd.write(" C_script_%s = script_%s\n" % (mkname, script))
            for condname in scripts['COND']:
                fd.write("endif\n")
            if not os.path.exists(os.path.join(am['CWDRAW'], script)):
                am['BUILT_SOURCES'].append("$(C_" +mkname+ ")")
                am['CLEAN'].append("$(C_" +mkname+ ")")
        else:
            am['BUILT_SOURCES'].append(script)

        # add dependency on library for mil modules
        fd.write("script_%s: %s\n" % (script, script)) # a bit of a hack ....

        if sd == "$(sysconfdir)":
            fd.write("install-exec-local-%s: %s\n" % (script, script))
            fd.write("\t-mkdir -p $(DESTDIR)%s\n" % sd)
            fd.write("\t$(INSTALL) $(INSTALL_BACKUP) $< $(DESTDIR)%s/%s\n\n" % (sd, script))
            fd.write("uninstall-local-%s: \n" % script)
            fd.write("\t$(RM) $(DESTDIR)%s/%s\n\n" % (sd, script))
        else:
            fd.write("install-exec-local-%s: %s\n" % (script, script))
            fd.write("\t-mkdir -p $(DESTDIR)%s\n" % sd)
            fd.write("\t-$(RM) $(DESTDIR)%s/%s\n" % (sd, script))
            fd.write("\t$(INSTALL) -m0755 $< $(DESTDIR)%s/%s\n\n" % (sd, script))
            fd.write("uninstall-local-%s: \n" % script)
            fd.write("\t$(RM) $(DESTDIR)%s/%s\n\n" % (sd, script))

        if 'NOINST' not in scripts:
            am['INSTALL'].append(s)
            am['UNINSTALL'].append(s)
            am['InstallList'].append("\t"+sd+"/"+script+cond+"\n")

    am_find_ins(am, scripts)
    am_deps(fd, scripts['DEPS'], am)

# return the unique elements of the argument list
def uniq(l):
    try:
        return list(set(l))
    except NameError:                   # presumably set() is unknown
        u = {}
        for x in l:
            u[x] = 1
        return u.keys()

# list of headers to install
def am_headers(fd, var, headers, am):

    sd = "includedir"
    if "DIR" in headers:
        sd = headers["DIR"][0] # use first name given
    sd = am_translate_dir(sd, am)

    hdrs_ext = headers['HEADERS']
    deps = []
    for d,srcs in headers['DEPS'].items():
        for s in srcs:
            if s in headers['SOURCES']:
                deps.append(d)
                break
    for header in uniq(headers['TARGETS'] + deps):
        h, ext = split_filename(header)
        if ext not in hdrs_ext:
            continue
        cond = ''
        h = header
        if 'COND' in headers:
            cond = '#' + '+'.join(headers['COND'])
            mkname = am_normalize(header.replace('.', '_'))
            for condname in headers['COND']:
                fd.write('if %s\n' % condname)
            fd.write('C_%s = %s\n' % (mkname, header))
            h = '$(C_%s)' % mkname
            for condname in headers['COND']:
                fd.write('endif\n')
        if cond:
            fd.write("uninstall-local-:\n")
            fd.write("install-exec-local-:\n")
        fd.write("install-exec-local-%s: %s\n" % (header, header))
        fd.write("\t-mkdir -p $(DESTDIR)%s\n" % sd)
        fd.write("\t-$(RM) $(DESTDIR)%s/%s\n" % (sd, header))
        fd.write("\t$(INSTALL_DATA) $< $(DESTDIR)%s/%s\n\n" % (sd, header))
        fd.write("uninstall-local-%s: \n" % header)
        fd.write("\t$(RM) $(DESTDIR)%s/%s\n\n" % (sd, header))
        am['INSTALL'].append(h)
        am['UNINSTALL'].append(h)
        if header not in headers['SOURCES']:
            am['BUILT_SOURCES'].append(h)
            am['CLEAN'].append(h)
        am['InstallList'].append("\t%s/%s%s\n" % (sd, header, cond))

    am_find_ins(am, headers)
    am_deps(fd, headers['DEPS'], am)
    for src in headers['SOURCES']:
        am['EXTRA_DIST'].append(src)

def am_normalize(name):
    return name.replace('-', '_')

def am_binary(fd, var, binmap, am):

    if type(binmap) == type([]):
        name = var[4:]
        if name == 'SCRIPTS':
            for script in binmap:
                if script not in am['BIN_SCRIPTS']:
                    am['BIN_SCRIPTS'].append(script)
            am['INSTALL'].append(name)
            am['UNINSTALL'].append(name)
            am['ALL'].append(name)
            for i in binmap:
                am['InstallList'].append("\t$(bindir)/%s\n" % i)
        else: # link
            binmap = binmap[0]
            if '?' in binmap:
                cond, binmap = binmap.split('?', 1)
            else:
                cond = ''
            src = binmap[4:]
            if cond:
                fd.write('if %s\n' % cond)
                cond = '#'+cond
            fd.write("install-exec-local-%s: %s\n" % (name, src))
            fd.write("\t-mkdir -p $(DESTDIR)$(bindir)\n")
            fd.write("\t-$(RM) $(DESTDIR)$(bindir)/%s\n" % name)
            fd.write("\tcd $(DESTDIR)$(bindir); $(LN_S) %s %s\n\n" % (src, name))
            fd.write("uninstall-local-%s: \n" % name)
            fd.write("\t$(RM) $(DESTDIR)$(bindir)/%s\n\n" % name)
            am['INSTALL'].append(name)
            am['UNINSTALL'].append(name)
            am['InstallList'].append("\t$(bindir)/"+name+cond+"\n")

            fd.write("all-local-%s: %s\n" % (name, src))
            fd.write("\t-$(RM) %s\n" % name)
            fd.write("\t$(LN_S) %s %s\n\n" % (src, name))
            am['CLEAN'].append(name)
            if cond:
                fd.write('else\n')
                fd.write("install-exec-local-%s:\n" % name)
                fd.write("uninstall-local-%s:\n" % name)
                fd.write("all-local-%s:\n" % name)
                fd.write('endif\n')
            am['ALL'].append(name)
        return

    SCRIPTS = []
    scripts_ext = []
    if 'SCRIPTS' in binmap:
        scripts_ext = binmap['SCRIPTS']

    name = var[4:]
    if "NAME" in binmap:
        binname = binmap['NAME'][0]
    else:
        binname = name
    norm_binname = am_normalize(binname)

    bd = 'bindir'
    if "DIR" in binmap:
        bd = binmap["DIR"][0] # use first name given
    bd = am_translate_dir(bd, am)
    fd.write("%sdir = %s\n" % (norm_binname, bd))

    cname = name
    cond = ''
    if 'COND' in binmap:
        for condname in binmap['COND']:
            fd.write("if %s\n" % condname)
        cond = '#' + '+'.join(binmap['COND'])
        fd.write(" C_%s = %s\n" % (name,name))
        fd.write(" %s_PROGRAMS =%s\n" % (norm_binname,  binname))
        for condname in binmap['COND']:
            fd.write("endif\n")
        cname = "$(C_" + name + ")"
    elif 'CONDINST' in binmap:
        for condname in binmap['CONDINST']:
            fd.write("if %s\n" % condname)
        cond = '#' + '+'.join(binmap['CONDINST'])
        fd.write(" C_inst_%s = %s\n" % (name, name))
        fd.write(" C_noinst_%s = \n" % (name))
        for condname in binmap['CONDINST']:
            fd.write("endif\n")

        for condname in binmap['CONDINST']:
            fd.write("if !%s\n" % condname)
        fd.write(" C_inst_%s = \n" % (name))
        fd.write(" C_noinst_%s = %s\n" % (name, name))
        for condname in binmap['CONDINST']:
            fd.write("endif\n")
        cname = "$(C_inst_" + name + ")"
        am['BINS'].append(cname)
        cname = "$(C_noinst_" + name + ")"
        am['NBINS'].append(cname)
        cname = ''
    elif 'NOINST' in binmap:
        am['NBINS'].append(binname)
    else:
        am['BINS'].append(binname)

    am['InstallList'].append("\t%s/%s%s\n" % (bd, binname, cond))

    if 'MTSAFE' in binmap:
        fd.write("CFLAGS %s $(THREAD_SAVE_FLAGS)\n" % am_assign)

    if "LIBS" in binmap:
        fd.write(am_additional_libs(norm_binname, "", "BIN", binmap["LIBS"], am))

    if "LDFLAGS" in binmap:
        ldflags = binmap["LDFLAGS"][:]
    else:
        ldflags = []
    ldflags.append('-export-dynamic')
    if 'NOINST' in binmap:
        ldflags.append('-no-install')
    fd.write(am_additional_flags(norm_binname, "", "BIN", ldflags, am))

    for src in binmap['SOURCES']:
        base, ext = split_filename(src)
        am['EXTRA_DIST'].append(src)

    nsrcs = "nodist_"+norm_binname+"_SOURCES ="
    srcs = "dist_"+norm_binname+"_SOURCES ="
    for target in binmap['TARGETS']:
        t, ext = split_filename(target)
        if ext in scripts_ext:
            if target not in SCRIPTS:
                SCRIPTS.append(target)
        elif ext in ('o', 'glue.o', 'tab.o', 'yy.o'):
            dist, src = am_find_srcs(target, binmap['DEPS'], am, cond)
            if src in binmap['SOURCES']:
                dist = True
            if dist:
                srcs = srcs + " " + src
            else:
                nsrcs = nsrcs + " " + src

    fd.write(nsrcs + "\n")
    fd.write(srcs + "\n")
    if len(SCRIPTS) > 0:
        fd.write("%s_scripts =%s\n" % (norm_binname, am_list2string(SCRIPTS, " ", "")))
        am['BUILT_SOURCES'].append("$(" + name + "_scripts)")
        fd.write("all-local-%s: $(%s_scripts)\n" % (name, name))
        am['ALL'].append(cname)

    am_find_hdrs(am, binmap)
    am_find_ins(am, binmap)

    am_deps(fd, binmap['DEPS'], am)

def am_bins(fd, var, binsmap, am):

    lbins = []
    scripts_ext = []
    if 'SCRIPTS' in binsmap:
        scripts_ext = binsmap['SCRIPTS']

    name = ""
    if "NAME" in binsmap:
        name = binsmap["NAME"][0] # use first name given
    if 'MTSAFE' in binsmap:
        fd.write("CFLAGS %s $(THREAD_SAVE_FLAGS)\n" % am_assign)
    for binsrc in binsmap['SOURCES']:
        SCRIPTS = []
        bin, ext = split_filename(binsrc)
        am['EXTRA_DIST'].append(binsrc)

        if 'CONDINST' in binsmap:
            for condname in binsmap['CONDINST']:
                fd.write("if %s\n" % condname)
            cond = '#' + '+'.join(binsmap['CONDINST'])
            fd.write(" C_inst_%s = %s\n" % (bin, bin))
            fd.write(" C_noinst_%s = \n" % (bin))
            for condname in binsmap['CONDINST']:
                fd.write("endif\n")

            for condname in binsmap['CONDINST']:
                fd.write("if !%s\n" % condname)
            cond = '#!' + '+'.join(binsmap['CONDINST'])
            fd.write(" C_inst_%s = \n" % (bin))
            fd.write(" C_noinst_%s = %s\n" % (bin, bin))
            for condname in binsmap['CONDINST']:
                fd.write("endif\n")
            cname = "$(C_inst_" + bin + ")"
            am['BINS'].append(cname)
            cname = "$(C_noinst_" + bin + ")"
            am['NBINS'].append(cname)
            cname = ''
        elif 'NOINST' in binsmap:
            am['NBINS'].append(bin)
        else:
            am['BINS'].append(bin)
            if "DIR" in binsmap:
                lbins.append(bin)

        if bin + "_LIBS" in binsmap:
            fd.write(am_additional_libs(bin, "", "BIN", binsmap[bin + "_LIBS"], am))
        elif "LIBS" in binsmap:
            fd.write(am_additional_libs(bin, "", "BIN", binsmap["LIBS"], am))

        if "LDFLAGS" in binsmap:
            ldflags = binsmap["LDFLAGS"][:]
        else:
            ldflags = []
        ldflags.append('-export-dynamic')
        if 'NOINST' in binsmap:
            ldflags.append('-no-install')
        fd.write(am_additional_flags(bin, "", "BIN", ldflags, am))

        nsrcs = "nodist_"+am_normalize(bin)+"_SOURCES ="
        srcs = "dist_"+am_normalize(bin)+"_SOURCES ="
        for target in binsmap['TARGETS']:
            t, ext = split_filename(target)
            if t == bin:
                t, ext = split_filename(target)
                if ext in scripts_ext:
                    if target not in SCRIPTS:
                        SCRIPTS.append(target)
                else:
                    dist, src = am_find_srcs(target, binsmap['DEPS'], am, None)
                    if src == binsrc:
                        dist = True
                    if dist:
                        srcs = srcs + " " + src
                    else:
                        nsrcs = nsrcs + " " + src
        fd.write(nsrcs + "\n")
        fd.write(srcs + "\n")

        if len(SCRIPTS) > 0:
            fd.write("%s_scripts = %s\n\n" % (name, am_list2string(SCRIPTS, " ", "")))
            am['BUILT_SOURCES'].append("$(" + name + "_scripts)")
            fd.write("all-local-%s: $(%s_scripts)\n" % (name, name))
            am['ALL'].append(name)

    if (len(lbins) > 0):
        bd = binsmap["DIR"][0] # use first name given
        bd = am_translate_dir(bd, am)
        fd.write("%sdir = %s\n" % (bin, bd))
        fd.write("%s_PROGRAMS =%s\n" % (bin,  am_list2string(lbins, " ", "") ))
        for bn in lbins:
            am['InstallList'].append("\t%s/%s\n" % (bd, bn))

    if 'HEADERS' in binsmap:
        HDRS = []
        hdrs_ext = binsmap['HEADERS']
        for target in binsmap['DEPS'].keys():
            t, ext = split_filename(target)
            if ext in hdrs_ext:
                am['HDRS'].append(target)
                if ext not in automake_ext:
                    am['EXTRA_DIST'].append(target)

    am_find_ins(am, binsmap)
    am_deps(fd, binsmap['DEPS'], am)

def am_mods_to_libs(fd, var, modmap, am):
    modname = var[:-4]+"LIBS"
    am_assignment(fd, var, modmap, am)
    fd.write(am_additional_libs(modname, "_", "MOD", modmap, am))

def am_library(fd, var, libmap, am):
    name = var[4:]

    sep = ""
    pref = 'lib'
    if "NAME" in libmap:
        libname = libmap['NAME'][0]
    else:
        libname = name

    if "PREFIX" in libmap:
        if libmap['PREFIX']:
            pref = libmap['PREFIX'][0]
        else:
            pref = ''

    if libname[0] == "_":
        sep = "_"
        libname = libname[1:]
    if 'SEP' in libmap:
        sep = libmap['SEP'][0]

    cname = libname
    cond = ''
    condname = ''
    if 'COND' in libmap:
        for condname in libmap['COND']:
            fd.write("if %s\n" % condname)
        fd.write(" C_%s = %s\n" % (libname, libname))
        cname = "$(C_" + libname + ")"
        cond = '#' + condname

    if name[0] == '_':
        name = name[1:]
    fd.write("lib%s%s_la_CFLAGS=-DLIB%s $(AM_CFLAGS)\n" % (sep,libname,name.upper()))

    ld = "libdir"
    if "DIR" in libmap:
        ld = libmap["DIR"][0] # use first name given

    SCRIPTS = []
    scripts_ext = []
    if 'SCRIPTS' in libmap:
        scripts_ext = libmap['SCRIPTS']

    ld = am_translate_dir(ld, am)
    fd.write("%sdir = %s\n" % (libname, ld))
    if 'NOINST' in libmap:
        am['NLIBS'].append((pref, libname, sep))
    else:
        am['LIBS'].append((pref, libname, sep, libmap.get('COND', ())))
        am['InstallList'].append("\t%s/%s%s%s.so%s\n" % (ld, pref, sep, libname, cond))

    if 'MTSAFE' in libmap:
        fd.write("CFLAGS %s $(THREAD_SAVE_FLAGS)\n" % am_assign)

    if "LIBS" in libmap:
        fd.write(am_additional_libs(libname, sep, "LIB", libmap["LIBS"], am, pref))
        fd.write(am_additional_install_libs(libname, sep, libmap["LIBS"], am))

    ldflags = []
    if 'MODULE' in libmap:
        ldflags.append('-module')
        ldflags.append('-avoid-version')
    if "LDFLAGS" in libmap:
        for x in libmap["LDFLAGS"]:
            ldflags.append(x)
    if 'VERSION' in libmap:
        ldflags.append('-version-info')
        ldflags.append(libmap['VERSION'][0])

    for src in libmap['SOURCES']:
        base, ext = split_filename(src)
        am['EXTRA_DIST'].append(src)

    if cond:
        for condname in libmap['COND']:
            fd.write("endif\n")

    fullpref = pref+sep+libname+'_la'
    nsrcs = "nodist_"+fullpref+"_SOURCES ="
    srcs = "dist_"+fullpref+"_SOURCES ="
    deps = []
    for target in libmap['TARGETS']:
        t, ext = split_filename(target)
        if ext in scripts_ext:
            if target not in SCRIPTS:
                SCRIPTS.append(target)
        else:
            dist, src = am_find_srcs(target, libmap['DEPS'], am, cond)
            if src in libmap['SOURCES']:
                dist = True
            if dist:
                srcs = srcs + " " + src
            else:
                nsrcs = nsrcs + " " + src
            if target[-2:] == '.o' and target in libmap['DEPS']:
                am_dep(fd, target, libmap['DEPS'][target], am, fullpref+"-")
                basename = target[:-2]
                fd.write('\t$(LIBTOOL) --tag=CC --mode=compile $(CC) $(DEFS) $(DEFAULT_INCLUDES) $(INCLUDES) $(AM_CPPFLAGS) $(CPPFLAGS) $(%s_CFLAGS) $(CFLAGS) $(%s_CFLAGS) -c -o %s-%s.lo `test -f \'%s.c\' || echo \'$(srcdir)/\'`%s.c\n' % (fullpref, basename, fullpref, basename, basename, basename))
            elif target[-4:] == '.def':
                ldflags.append("-export-symbols")
                ldflags.append(target)
                deps.append(target)
    fd.write(nsrcs + "\n")
    fd.write(srcs + "\n")
    if 'XDEPS' in libmap:
        fd.write(fullpref + '_DEPENDENCIES =')
        for dep in libmap['XDEPS']:
            fd.write(' ')
            fd.write(dep)
        fd.write('\n')

    if deps:
        fd.write(am_additional_deps(libname, sep, "LIB", deps, am, pref))
    if ldflags:
        fd.write(am_additional_flags(libname, sep, "LIB", ldflags, am, pref))

    if len(SCRIPTS) > 0:
        fd.write("%s_scripts = %s\n" % (libname, am_list2string(SCRIPTS, " ", "")))
        am['BUILT_SOURCES'].append("$(" + libname + "_scripts)")
        fd.write("all-local-%s: $(%s_scripts)\n" % (libname, libname))
        am['ALL'].append(cname)

    am_find_hdrs(am, libmap)
    am_find_ins(am, libmap)

    am_deps(fd, libmap['DEPS'], am)

def am_python_generic(fd, var, python, am, PYTHON):
    pyre = re.compile(r'packages *= *\[ *(.*[^ ]) *\]')
    pynmre = re.compile('name *= *([\'"])([^\'"]+)\\1')
    fd.write('all-local-%s:\n' % var)
    am['ALL'].append(var)
    am['INSTALL'].append(var)
    am['UNINSTALL'].append(var)
    pkgdirs = []
    pkgnams = []
    for f in python['FILES']:
        fd.write("\t[ '$(srcdir)' -ef . ] || cp -p '$(srcdir)/%s' '%s'\n" % (f, f))
        pkgs = map(lambda x: x.strip('\'" '),
                   pyre.search(open(os.path.join(am['CWDRAW'], f)).read()).group(1).split(', '))
        pkgnams.append(pynmre.search(open(os.path.join(am['CWDRAW'], f)).read()).group(2))
        for pkg in pkgs:
            pkgdir = posixpath.join(*pkg.split('.'))
            pkgdirs.append(pkgdir)
            fd.write("\t[ '$(srcdir)' -ef . ] || mkdir -p '%s'\n" % pkgdir)
            fd.write("\t[ '$(srcdir)' -ef . ] || cp -p '$(srcdir)/%s'/*.py '%s'\n" % (pkgdir, pkgdir))
        fd.write("\t[ '$(srcdir)' -ef . ] || cp -p '$(srcdir)/README.rst' .\n")
        fd.write("\t$(%s) '%s' build\n" % (PYTHON, f))
    fd.write('install-exec-local-%s:\n' % var)
    for f in python['FILES']:
        # see buildtools/conf/rules.mk for PY_INSTALL_LAYOUT
        # it is needed to install into dist-packages on Debian/Ubuntu
        fd.write("\t$(%s) '%s' install $(PY_INSTALL_LAYOUT) --prefix='$(DESTDIR)$(prefix)'\n" % (PYTHON, f))
    fd.write('uninstall-local-%s:\n' % var)
    for pkgdir in sorted(pkgdirs, reverse = True):
        fd.write("\trm -r '$(DESTDIR)$(prefix)/$(%s_LIBDIR)/%s'\n" % (PYTHON, pkgdir))
    for name in pkgnams:
        fd.write("\trm '$(DESTDIR)$(prefix)/$(%s_LIBDIR)'/%s-*.egg-info\n" % (PYTHON, name.replace('-', '_')))
    fd.write('mostlyclean-local:\n')
    for pkgdir in sorted(pkgdirs, reverse = True):
        fd.write("\t[ '$(srcdir)' -ef . -o ! -d '%s' ] || rm -r '%s'\n" % (pkgdir, pkgdir))

def am_python2(fd, var, python, am):
    am_python_generic(fd, var, python, am, 'PYTHON2')

def am_python3(fd, var, python3, am):
    am_python_generic(fd, var, python3, am, 'PYTHON3')

def am_ant(fd, var, ant, am):

    target = var[4:]                    # the ant target to call

    jd = "JAVADIR"
    if "DIR" in ant:
        jd = ant["DIR"][0] # use first name given
    jd = am_translate_dir(jd, am)

    #if "SOURCES" in ant:
        #for src in ant['SOURCES']:
            #am['EXTRA_DIST'].append(src)

    fd.write("\nif HAVE_JAVA\n\n")  # there is ant if configure set HAVE_JAVA

    if "COND" in ant:
        fd.write("\nif " + ant["COND"][0] +"\n\n")

    fd.write("\n%s_ant_target:\n\t\"$(ANT)\" -f \"`$(anttranslatepath) $(srcdir)/build.xml`\" -Dbuilddir=\"`$(anttranslatepath) $(PWD)`/%s\" -Djardir=\"`$(anttranslatepath) $(PWD)`\" -Dbasedir=\"`$(anttranslatepath) $(srcdir)`\" %s\n" % (target, target, target))

    for file in ant['FILES']:
        sfile = file.replace(".", "_")
        fd.write("\n%s: %s_ant_target\n" % (file, target))

        fd.write("install-exec-local-%s: %s\n" % (sfile, file))
        fd.write("\t-mkdir -p $(DESTDIR)%s\n" % jd)
        fd.write("\t$(INSTALL) $< $(DESTDIR)%s/%s\n" % (jd, file))

        fd.write("uninstall-local-%s:\n" % sfile)
        fd.write("\t$(RM) $(DESTDIR)%s/%s\n" % (jd, file))

        fd.write("all-local-%s: %s\n" % (sfile, file))

        am['ALL'].append(sfile)

    if "COND" in ant:
        fd.write("\nelse\n\n")

    for file in ant['FILES']:
        sfile = file.replace(".", "_")
        fd.write("install-exec-local-%s:\n" % sfile)
        fd.write("uninstall-local-%s:\n" % sfile)
        fd.write("all-local-%s:\n" % sfile)

    if "COND" in ant:
        fd.write("\nendif !" + ant["COND"][0] + "\n\n")

    fd.write("\nelse\n\n")

    for file in ant['FILES']:
        sfile = file.replace(".", "_")
        fd.write("install-exec-local-%s:\n" % sfile)
        fd.write("uninstall-local-%s:\n" % sfile)
        fd.write("all-local-%s:\n" % sfile)

    fd.write("\nendif !HAVE_JAVA\n\n")

    if "COND" in ant:
        cond = "#" + ant["COND"][0]
    else:
        cond = ""
    for file in ant['FILES']:
        sfile = file.replace(".", "_")
        am['INSTALL'].append(sfile)
        am['UNINSTALL'].append(sfile)
        am['InstallList'].append("\t" + jd + "/" + file + cond + "\n")

def am_add_srcdir(path, am, prefix =""):
    dir = path
    if dir[0] == '$':
        return ""
    elif not posixpath.isabs(dir):
        dir = "$(srcdir)/" + dir
    else:
        return ""
    return prefix+dir

def am_translate_dir(path, am):
    # translate any \ path separators to / -- the generated file is
    # Unix/Linux/Cygwin only
    path = path.replace('\\', '/')
    dir = path
    rest = ""
    if path.find('/') >= 0:
        dir, rest = path.split('/', 1)
        rest = '/' + rest

    if dir in ('bindir', 'builddir', 'datadir', 'includedir', 'infodir',
               'libdir', 'libexecdir', 'localstatedir', 'mandir',
               'oldincludedir', 'pkgbindir', 'pkgdatadir', 'pkgincludedir',
               'pkglibdir', 'pkglocalstatedir', 'pkgsysconfdir', 'sbindir',
               'sharedstatedir', 'srcdir', 'sysconfdir', 'top_builddir',
               'top_srcdir', 'prefix'):
        dir = "$("+dir+")"
    dir = dir + rest
    return dir

def am_includes(fd, var, values, am):
    incs = "-I$(srcdir)"
    for i in values:
        if i[:2] == "-I" and i[2] != "$":
            i = i[2:]
        if i[0] == "-" or i[0] == "$":
            incs = incs + " " + i
        else:
            incs = incs + " -I" + am_translate_dir(i, am) \
                   + am_add_srcdir(i, am, " -I")
    fd.write("AM_CPPFLAGS = " + incs + "\n")

output_funcs = {'SUBDIRS': am_subdirs,
                'EXTRA_DIST': am_extra_dist,
                'EXTRA_DIST_DIR': am_extra_dist_dir,
                'EXTRA_HEADERS': am_extra_headers,
                'LIBDIR': am_libdir,
                'LIB': am_library,
                'BINS': am_bins,
                'BIN': am_binary,
                'INCLUDES': am_includes,
                'MTSAFE': am_mtsafe,
                'SCRIPTS': am_scripts,
                'CFLAGS': am_cflags,
                'STATIC_MODS': am_mods_to_libs,
                'smallTOC_SHARED_MODS': am_mods_to_libs,
                'largeTOC_SHARED_MODS': am_mods_to_libs,
                'HEADERS': am_headers,
                'ANT': am_ant,
                'PYTHON2': am_python2,
                'PYTHON3': am_python3,
                }

def output(tree, cwd, topdir, automake, conditional):
    global am_assign
    #if int(automake) >= 1005000 and int(automake) < 1006000:
    #    am_assign = "="

    # use binary mode since automake on Cygwin can't deal with \r\n
    # line endings
    fd = open(os.path.join(cwd, 'Makefile.am'), "w")

    fd.write('''
## This file is generated by autogen.py, do not edit
## Process this file with automake to produce Makefile.in
## autogen includes dependencies so automake doesn\'t need to generated them

AUTOMAKE_OPTIONS = no-dependencies 1.4 foreign

''')

    if cwd == topdir:
        fd.write('ACLOCAL_AMFLAGS = -I buildtools/conf\n')

    if 'INCLUDES' not in tree:
        tree.add('INCLUDES', [])

    am = {}
    if 'NAME' in tree:
        am['NAME'] = tree['NAME']
    else:
        if cwd != topdir:
            am['NAME'] = os.path.basename(cwd)
        else:
            am['NAME'] = ''

    name = am['NAME']
    am['TOPDIR'] = topdir
    am['CWD'] = ''
    if cwd != topdir:
        # in case we happen to be running this on Windows, replace dir seps
        am['CWD'] = cwd[len(topdir)+1:].replace('\\', '/')+'/'
    am['CWDRAW'] = cwd                  # unedited working directory
    am['BUILT_SOURCES'] = []            # generated source files
    am['CLEAN'] = []                    # files to be cleaned with make clean
    am['EXTRA_DIST'] = []
    am['LIBS'] = []                     # all libraries (am_library)
    am['NLIBS'] = []                    # all libraries which are not installed
    am['BINS'] = []
    am['NBINS'] = []
    am['BIN_SCRIPTS'] = []
    am['INSTALL'] = []
    am['DATA_INSTALL'] = []
    am['UNINSTALL'] = []
    am['HDRS'] = []
    am['LIBDIR'] = "libdir"
    am['ALL'] = []
    am['DEPS'] = []
    if conditional:
        cond = '#' + '+'.join(conditional)
    else:
        cond = ''
    am['InstallList'] = []
    am['InstallList'].append(am['CWD']+cond+"\n")
    am['DocList'] = []
    am['DocList'].append(am['CWD']+cond+"\n")
    am['OutList'] = [am['CWD'] + 'Makefile']

    for i, v in tree.items():
        j = i
        if i.find('_') >= 0:
            k, j = i.split('_', 1)
            j = k.upper()
        if i in output_funcs:
            output_funcs[i](fd, i, v, am)
        elif j in output_funcs:
            output_funcs[j](fd, i, v, am)
        elif i != 'TARGETS':
            am_assignment(fd, i, v, am)

    fd.write("BUILT_SOURCES =%s\n" % am_list2string(am['BUILT_SOURCES'], " ", ""))
    fd.write("MOSTLYCLEANFILES =%s\n" % am_list2string(am['CLEAN'], ' ', ''))

    fd.write("EXTRA_DIST = Makefile.ag Makefile.msc%s\n" % \
          am_list2string(am['EXTRA_DIST'], " ", ""))
##     fd.write(" $(BUILT_SOURCES)\n")

    if am['LIBS']:
        lib = 'lib'
        ld = am['LIBDIR']
        ld = am_translate_dir(ld, am)
        if ld != '$(libdir)':
            fd.write("agdir = %s\n" % ld)
            lib = 'ag'

        libs = am_sort_libs(am['LIBS'], tree)
        s = ""
        for (pref, lib, sep, cond) in am['LIBS']:
            if cond:
                for condname in cond:
                    fd.write("if %s\n" % condname)
                fd.write("%s_LTLIBRARIES = %s%s%s.la\n" % (lib, pref, sep, lib))
                for condname in cond:
                    fd.write("endif\n")
            else:
                fd.write("%s_LTLIBRARIES = %s%s%s.la\n" % (lib, pref, sep, lib))

    if am['NLIBS']:
        fd.write("noinst_LTLIBRARIES =")
        for (pref, lib, sep) in am['NLIBS']:
            fd.write(" %s%s%s.la" % (pref, sep, lib))
        fd.write("\n")
        for (pref, lib, sep) in am['NLIBS']:
            fd.write('install-%sLTLIBRARIES:\n' % lib)

    if am['NBINS']:
        fd.write("noinst_PROGRAMS =%s\n" % am_list2string(am['NBINS'], " ", ""))

    if len(am['BINS']) > 0:
        fd.write("bin_PROGRAMS =%s\n" % am_list2string(am['BINS'], " ", ""))
        for i in am['BINS']:
            am['InstallList'].append("\t$(bindir)/"+i+"\n")

    if len(am['BIN_SCRIPTS']) > 0:
        scripts = am['BIN_SCRIPTS']
        fd.write("bin_SCRIPTS =%s\n" % am_list2string(scripts, " ", ""))
        fd.write("install-exec-local-SCRIPTS: \n")
        fd.write("all-local-SCRIPTS: $(bin_SCRIPTS)\n")

    if len(am['UNINSTALL']) > 0:
        fd.write("uninstall-local:%s\n" % \
            am_list2string(am['UNINSTALL'], " uninstall-local-", ""))

    if len(am['INSTALL']) > 0:
        fd.write("install-exec-local:%s\n" % \
            am_list2string(am['INSTALL'], " install-exec-local-", ""))

    if len(am['DATA_INSTALL']) > 0:
        fd.write("install-data-local:%s\n" % \
            am_list2string(am['DATA_INSTALL'], " install-data-local-", ""))

    if len(am['ALL']) > 0:
        fd.write("all-local:%s\n" % \
            am_list2string(am['ALL'], " all-local-", ""))

    if len(am['HDRS']) > 0:
        if len(name) > 0:
            fd.write("%sincludedir = $(pkgincludedir)/%s\n" % (name, name))
        else:
            name="top"
            fd.write("%sincludedir = $(pkgincludedir)\n" % (name))
        fd.write("nodist_%sinclude_HEADERS =%s\n" % (name, am_list2string(am['HDRS'], " ", "")))

    fd.write('''
  include $(top_srcdir)/buildtools/conf/rules.mk
''')
    if cwd == topdir:
        fd.write('include $(top_builddir)/rpm.mk\n')
    fd.close()

    return am['InstallList'], am['DocList'], am['OutList']

# vim:ts=4 sw=4 expandtab:
