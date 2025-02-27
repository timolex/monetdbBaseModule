
#include "monetdb_config.h"
#include "rel_rel.h"
#include "rel_exp.h"
#include "rel_prop.h"
#include "rel_remote.h"
#include "sql_mvc.h"

/* we don't name relations directly, but sometimes we need the relation
   name. So we look it up in the first expression

   we should clean up (remove) this function.
 */
const char *
rel_name( sql_rel *r )
{
	if (!is_project(r->op) && !is_base(r->op) && r->l)
		return rel_name(r->l);
	if (r->exps && list_length(r->exps)) {
		sql_exp *e = r->exps->h->data;
		if (e->rname)
			return e->rname;
		if (e->type == e_column)
			return e->l;
	}
	return NULL;
}

sql_rel *
rel_distinct(sql_rel *l)
{
	if (l->card >= CARD_AGGR) /* in case of CARD_AGGR, we could
	                             do better, ie check the group by
	                             list etc */
		set_distinct(l);
	return l;
}

sql_rel *
rel_dup(sql_rel *r)
{
	sql_ref_inc(&r->ref);
	return r;
}

static void
rel_destroy_(sql_rel *rel)
{
	if (!rel)
		return;
	if (is_join(rel->op) ||
	    is_semi(rel->op) ||
	    is_select(rel->op) ||
	    is_set(rel->op) ||
	    rel->op == op_topn ||
		rel->op == op_sample) {
		if (rel->l)
			rel_destroy(rel->l);
		if (rel->r)
			rel_destroy(rel->r);
	} else if (is_project(rel->op)) {
		if (rel->l)
			rel_destroy(rel->l);
	} else if (is_modify(rel->op)) {
		if (rel->r)
			rel_destroy(rel->r);
	}
}

void
rel_destroy(sql_rel *rel)
{
	if (!rel)
		return;
	if (sql_ref_dec(&rel->ref) > 0)
		return;
	rel_destroy_(rel);
}

sql_rel*
rel_create( sql_allocator *sa )
{
	sql_rel *r = SA_NEW(sa, sql_rel);

	sql_ref_init(&r->ref);
	r->l = r->r = NULL;
	r->exps = NULL;
	r->nrcols = 0;
	r->flag = 0;
	r->card = CARD_ATOM;
	r->processed = 0;
	r->subquery = 0;
	r->p = NULL;
	return r;
}

sql_rel *
rel_copy( sql_allocator *sa, sql_rel *i )
{
	sql_rel *rel = rel_create(sa);

	rel->l = NULL;
	rel->r = NULL;
	rel->card = i->card;

	switch(i->op) {
	case op_basetable:
		rel->l = i->l;
		break;
	case op_table:
		rel->l = i->l;
		rel->r = i->r;
		break;
	case op_groupby:
		rel->l = rel_copy(sa, i->l);
		if (i->r)
			rel->r = (i->r)?list_dup(i->r, (fdup)NULL):NULL;
		break;
	case op_join:
	case op_left:
	case op_right:
	case op_full:
	case op_apply:
	case op_semi:
	case op_anti:
	case op_addition:
	case op_project:
	case op_select:
	default:
		if (i->l)
			rel->l = rel_copy(sa, i->l);
		if (i->r)
			rel->r = rel_copy(sa, i->r);
		break;
	}
	rel->op = i->op;
	rel->exps = (i->exps)?list_dup(i->exps, (fdup)NULL):NULL;
	return rel;
}

sql_rel *
rel_select_copy(sql_allocator *sa, sql_rel *l, list *exps)
{
	sql_rel *rel = rel_create(sa);
	
	rel->l = l;
	rel->r = NULL;
	rel->op = op_select;
	rel->exps = exps?list_dup(exps, (fdup)NULL):NULL;
	rel->card = CARD_ATOM; /* no relation */
	if (l) {
		rel->card = l->card;
		rel->nrcols = l->nrcols;
	}
	return rel;
}

static int
rel_issubquery(sql_rel*r)
{
	if (!r->subquery) {
		if (is_select(r->op))
			return rel_issubquery(r->l);
	}	
	return r->subquery;
}

static sql_rel *
rel_bind_column_(mvc *sql, sql_rel **p, sql_rel *rel, const char *cname )
{
	int ambiguous = 0;
	sql_rel *l = NULL, *r = NULL;
	switch(rel->op) {
	case op_join:
	case op_left:
	case op_right:
	case op_full: {
		sql_rel *right = rel->r;

		*p = rel;
		r = rel_bind_column_(sql, p, rel->r, cname);

		if (!r || !rel_issubquery(right)) {
			*p = rel;
			l = rel_bind_column_(sql, p, rel->l, cname);
			if (l && r && !rel_issubquery(r)) {
				(void) sql_error(sql, ERR_AMBIGUOUS, "SELECT: identifier '%s' ambiguous", cname);
				return NULL;
			}
		}
		if (sql->session->status == -ERR_AMBIGUOUS) 
			return NULL;
		if (l && !r)
			return l;
		return r;
	}
	case op_union:
	case op_except:
	case op_inter:
	case op_groupby:
	case op_addition:
	case op_project:
	case op_table:
	case op_basetable:
		if (rel->exps && exps_bind_column(rel->exps, cname, &ambiguous))
			return rel;
		if (ambiguous) {
			(void) sql_error(sql, ERR_AMBIGUOUS, "SELECT: identifier '%s' ambiguous", cname);
			return NULL;
		}
		*p = rel;
		if (is_processed(rel))
			return NULL;
		if (rel->l && !(is_base(rel->op)))
			return rel_bind_column_(sql, p, rel->l, cname );
		break;
	case op_apply:
	case op_semi:
	case op_anti:

	case op_select:
	case op_topn:
	case op_sample:
		*p = rel;
		if (rel->l)
			return rel_bind_column_(sql, p, rel->l, cname);
	default:
		return NULL;
	}
	return NULL;
}

sql_exp *
rel_bind_column( mvc *sql, sql_rel *rel, const char *cname, int f )
{
	sql_rel *p = NULL;

	if (f == sql_sel && rel && is_project(rel->op) && !is_processed(rel))
		rel = rel->l;

	if (!rel || (rel = rel_bind_column_(sql, &p, rel, cname)) == NULL)
		return NULL;

	if ((is_project(rel->op) || is_base(rel->op)) && rel->exps) {
		sql_exp *e = exps_bind_column(rel->exps, cname, NULL);
		if (e)
			return exp_alias_or_copy(sql, e->rname, cname, rel, e);
	}
	return NULL;
}

sql_exp *
rel_bind_column2( mvc *sql, sql_rel *rel, const char *tname, const char *cname, int f )
{
	(void)f;

	if (!rel)
		return NULL;

	if (rel->exps && (is_project(rel->op) || is_base(rel->op))) {
		sql_exp *e = exps_bind_column2(rel->exps, tname, cname);
		if (e)
			return exp_alias_or_copy(sql, tname, cname, rel, e);
	}
	if (is_project(rel->op) && rel->l) {
		if (!is_processed(rel))
			return rel_bind_column2(sql, rel->l, tname, cname, f);
	} else if (is_join(rel->op)) {
		sql_exp *e = rel_bind_column2(sql, rel->l, tname, cname, f);
		if (!e)
			e = rel_bind_column2(sql, rel->r, tname, cname, f);
		return e;
	} else if (is_set(rel->op) ||
		   is_sort(rel) ||
		   is_semi(rel->op) ||
		   is_apply(rel->op) ||
		   is_select(rel->op)) {
		if (rel->l)
			return rel_bind_column2(sql, rel->l, tname, cname, f);
	}
	return NULL;
}


sql_rel *
rel_inplace_setop(sql_rel *rel, sql_rel *l, sql_rel *r, operator_type setop, list *exps)
{
	rel_destroy_(rel);
	rel->l = l;
	rel->r = r;
	rel->op = setop;
	rel->exps = NULL;
	rel->card = CARD_MULTI;
	rel->flag = 0;
	if (l && r)
		rel->nrcols = l->nrcols + r->nrcols;
	rel->exps = exps;
	return rel;
}

sql_rel *
rel_inplace_project(sql_allocator *sa, sql_rel *rel, sql_rel *l, list *e)
{
	if (!l) {
		l = rel_create(sa);

		l->op = rel->op;
		l->l = rel->l;
		l->r = rel->r;
		l->exps = rel->exps;
		l->nrcols = rel->nrcols;
		l->flag = rel->flag;
		l->card = rel->card;
	} else {
		rel_destroy_(rel);
	}
	set_processed(rel);

	rel->l = l;
	rel->r = NULL;
	rel->op = op_project;
	rel->exps = e;
	rel->card = CARD_MULTI;
	rel->flag = 0;
	if (l) {
		rel->nrcols = l->nrcols;
		assert (exps_card(rel->exps) <= rel->card);
	}
	return rel;
}

sql_rel *
rel_inplace_groupby(sql_rel *rel, sql_rel *l, list *groupbyexps, list *exps )
{
	rel_destroy_(rel);
	rel->card = CARD_ATOM;
	if (groupbyexps) 
		rel->card = CARD_AGGR;
	rel->l = l;
	rel->r = groupbyexps;
	rel->exps = exps;
	rel->nrcols = l->nrcols;
	rel->op = op_groupby;
	rel->flag = 0;
	return rel;
}

sql_rel *
rel_setop(sql_allocator *sa, sql_rel *l, sql_rel *r, operator_type setop)
{
	sql_rel *rel = rel_create(sa);

	rel->l = l;
	rel->r = r;
	rel->op = setop;
	rel->exps = NULL;
	rel->card = CARD_MULTI;
	if (l && r)
		rel->nrcols = l->nrcols + r->nrcols;
	return rel;
}

sql_rel *
rel_crossproduct(sql_allocator *sa, sql_rel *l, sql_rel *r, operator_type join)
{
	sql_rel *rel = rel_create(sa);

	rel->l = l;
	rel->r = r;
	rel->op = join;
	rel->exps = NULL;
	rel->card = CARD_MULTI;
	rel->nrcols = l->nrcols + r->nrcols;
	return rel;
}

sql_rel *
rel_addition(sql_allocator *sa, sql_rel *l, operator_type addition)
{
	sql_rel *rel = rel_create(sa);

	rel->l = l;
	rel->r = NULL;
	rel->op = addition;
	rel->exps = NULL;
	rel->card = l->card;
	rel->nrcols = l->nrcols;
	return rel;
}

sql_rel *
rel_topn(sql_allocator *sa, sql_rel *l, list *exps )
{
	sql_rel *rel = rel_create(sa);

	rel->l = l;
	rel->r = NULL;
	rel->op = op_topn;	
	rel->exps = exps;
	rel->card = l->card;
	rel->nrcols = l->nrcols;
	return rel;
}

sql_rel *
rel_sample(sql_allocator *sa, sql_rel *l, list *exps )
{
	sql_rel *rel = rel_create(sa);

	rel->l = l;
	rel->r = NULL;
	rel->op = op_sample;
	rel->exps = exps;
	rel->card = l->card;
	rel->nrcols = l->nrcols;
	return rel;
}

sql_rel *
rel_label( mvc *sql, sql_rel *r, int all)
{
	int nr = ++sql->label;
	char tname[16], *tnme;
	char cname[16], *cnme = NULL;

	tnme = number2name(tname, 16, nr);
	if (!is_project(r->op)) {
		r = rel_project(sql->sa, r, rel_projections(sql, r, NULL, 1, 1));
		set_processed(r);
	}
	if (is_project(r->op) && r->exps) {
		node *ne = r->exps->h;

		for (; ne; ne = ne->next) {
			if (all) {
				nr = ++sql->label;
				cnme = number2name(cname, 16, nr);
			}
			exp_setname(sql->sa, ne->data, tnme, cnme );
		}
	}
	/* op_projects can have a order by list */
	if (r->op == op_project && r->r) {
		list *exps = r->r;
		node *ne = exps->h;

		for (; ne; ne = ne->next) {
			if (all) {
				nr = ++sql->label;
				cnme = number2name(cname, 16, nr);
			}
			exp_setname(sql->sa, ne->data, tnme, cnme );
		}
	}
	return r;
}

void
rel_project_add_exp( mvc *sql, sql_rel *rel, sql_exp *e)
{
	assert(is_project(rel->op));

	if (!e->rname) 
		exp_setrelname(sql->sa, e, sql->label);
	if (rel->op == op_project) {
		if (!rel->exps)
			rel->exps = new_exp_list(sql->sa);
		append(rel->exps, e);
		if (e->card > rel->card)
			rel->card = e->card;
	} else if (rel->op == op_groupby) {
		(void) rel_groupby_add_aggr(sql, rel, e);
	}
}

void
rel_select_add_exp(sql_allocator *sa, sql_rel *l, sql_exp *e)
{
	assert(l->op == op_select || is_outerjoin(l->op));
	if (e->type != e_cmp && e->card > CARD_ATOM) {
		sql_exp *t = exp_atom_bool(sa, 1);
		e = exp_compare(sa, e, t, cmp_equal);
	}
	append(l->exps, e);
}

void
rel_join_add_exp( sql_allocator *sa, sql_rel *rel, sql_exp *e)
{
	assert(is_join(rel->op) || is_semi(rel->op) || is_select(rel->op));

	if (!rel->exps)
		rel->exps = new_exp_list(sa);
	append(rel->exps, e);
	if (e->card > rel->card)
		rel->card = e->card;
}

static sql_exp * exps_match(sql_exp *m, sql_exp *e);

static int
explists_match(list *m, list *e)
{
	node *nm,*ne;

	if (!m || !e)
		return (m==e);
	if (list_length(m) != list_length(e))
		return 0;
	for (nm = m->h, ne = e->h; nm && ne; nm = nm->next, ne = ne->next) {
		if (!exps_match(nm->data, ne->data))
			return 0;
	}
	return 1;
}

static sql_exp *
exps_match(sql_exp *m, sql_exp *e)
{
	if (m->type != e->type)
		return NULL;
	switch (m->type) {
	case e_column:
		if (strcmp(m->r, e->r) == 0) {
			if (m->l && e->l && (strcmp(m->l, e->l) == 0))
				return m;
			else if (!m->l && !e->l)
				return m;
		}
		break;
	case e_aggr:
		if (m->f == e->f && explists_match(m->l, e->l))
			return m;
		break;
	default:
		return NULL;
	}
	return NULL;
}

static sql_exp *
exps_find_match_exp(list *l, sql_exp *e)
{
	node *n;
	if (!l || !list_length(l))
		return NULL;

	for (n = l->h; n; n = n->next){
		sql_exp *m = n->data;
		if (exps_match(m,e))
			return m;
	}
	return NULL;
}

sql_exp *
rel_groupby_add_aggr(mvc *sql, sql_rel *rel, sql_exp *e)
{
	sql_exp *m = NULL, *ne;
	char name[16], *nme = NULL;
	char *tname = NULL;

	if ((m=exps_find_match_exp(rel->exps, e)) == NULL) {
		if (!e->name) {
			nme = number2name(name, 16, ++sql->label);
			exp_setname(sql->sa, e, nme, nme);
		}
		append(rel->exps, e);
		m = e;
	}
	if (e->type == e_column)
		tname = e->l;
	ne = exp_column(sql->sa, tname, m->name, exp_subtype(m),
			rel->card, has_nil(m), is_intern(m));
	exp_setname(sql->sa, ne, NULL, e->name);
	return ne;
}

sql_rel *
rel_select(sql_allocator *sa, sql_rel *l, sql_exp *e)
{
	sql_rel *rel;
	
	if (l && is_outerjoin(l->op) && !is_processed(l)) {
		if (e) {
			if (!l->exps)
				l->exps = new_exp_list(sa);
			append(l->exps, e);
		}
		return l;
	}
		
	if (l && l->op == op_select && !rel_is_ref(l)) { /* refine old select */
		if (e)
			rel_select_add_exp(sa, l, e);
		return l;
	}
	rel = rel_create(sa);
	rel->l = l;
	rel->r = NULL;
	rel->op = op_select;
	rel->exps = new_exp_list(sa);
	if (e)
		rel_select_add_exp(sa, rel, e);
	rel->card = CARD_ATOM; /* no relation */
	if (l) {
		rel->card = l->card;
		rel->nrcols = l->nrcols;
	}
	return rel;
}

sql_rel *
rel_basetable(mvc *sql, sql_table *t, const char *atname)
{
	prop *p = NULL;
	node *cn;
	sql_allocator *sa = sql->sa;
	sql_rel *rel = rel_create(sa);
	const char *tname = t->base.name;

	assert(atname);
	rel->l = t;
	rel->r = NULL;
	rel->op = op_basetable;
	rel->exps = new_exp_list(sa);

	if (isRemote(t)) 
		tname = mapiuri_table(t->query, sql->sa, tname);
	for (cn = t->columns.set->h; cn; cn = cn->next) {
		sql_column *c = cn->data;
		sql_exp *e = exp_alias(sa, atname, c->base.name, tname, c->base.name, &c->type, CARD_MULTI, c->null, 0);

		if (c->t->pkey && ((sql_kc*)c->t->pkey->k.columns->h->data)->c == c) {
			p = e->p = prop_create(sa, PROP_HASHCOL, e->p);
			p->value = c->t->pkey;
		} else if (c->unique == 1) {
			p = e->p = prop_create(sa, PROP_HASHCOL, e->p);
			p->value = NULL;
		}
		append(rel->exps, e);
	}
	append(rel->exps, exp_alias(sa, atname, TID, tname, TID, sql_bind_localtype("oid"), CARD_MULTI, 0, 1));

	if (t->idxs.set) {
		for (cn = t->idxs.set->h; cn; cn = cn->next) {
			sql_exp *e;
			sql_idx *i = cn->data;
			sql_subtype *t = sql_bind_localtype("wrd"); /* hash "wrd" */
			char *iname = sa_strconcat( sa, "%", i->base.name);

			if (i->type == join_idx)
				t = sql_bind_localtype("oid"); 

			e = exp_alias(sa, atname, iname, tname, iname, t, CARD_MULTI, 0, 1);
			/* index names are prefixed, to make them independent */
			if (hash_index(i->type)) {
				p = e->p = prop_create(sa, PROP_HASHIDX, e->p);
				p->value = i;
			}
			if (i->type == join_idx) {
				p = e->p = prop_create(sa, PROP_JOINIDX, e->p);
				p->value = i;
			}
			append(rel->exps, e);
		}
	}

	rel->card = CARD_MULTI;
	rel->nrcols = list_length(t->columns.set);
	return rel;
}

sql_rel *
rel_groupby(mvc *sql, sql_rel *l, list *groupbyexps )
{
	sql_rel *rel = rel_create(sql->sa);
	list *aggrs = new_exp_list(sql->sa);
	node *en;

	rel->card = CARD_ATOM;
	if (groupbyexps) {
		rel->card = CARD_AGGR;
		for (en = groupbyexps->h; en; en = en->next) {
			sql_exp *e = en->data, *ne;

			/* after the group by the cardinality reduces */
			e->card = rel->card;
			if (!exp_name(e))
				exp_label(sql->sa, e, ++sql->label);
			ne = exp_column(sql->sa, exp_relname(e), exp_name(e), exp_subtype(e), exp_card(e), has_nil(e), 0);
			append(aggrs, ne);
		}
	}
	rel->l = l;
	rel->r = groupbyexps;
	rel->exps = aggrs;
	rel->nrcols = l->nrcols;
	rel->op = op_groupby;
	return rel;
}

sql_rel *
rel_project(sql_allocator *sa, sql_rel *l, list *e)
{
	sql_rel *rel = rel_create(sa);

	rel->l = l;
	rel->r = NULL;
	rel->op = op_project;
	rel->exps = e;
	rel->card = exps_card(e);
	if (l) {
		rel->card = l->card;
		rel->nrcols = l->nrcols;
	}
	return rel;
}

sql_rel *
rel_relational_func(sql_allocator *sa, sql_rel *l, list *exps)
{
	sql_rel *rel = rel_create(sa);

	rel->flag = 1;
	rel->l = l;
	rel->op = op_table;
	rel->exps = exps;
	rel->card = CARD_MULTI;
	rel->nrcols = list_length(exps);
	return rel;
}

static void
exps_has_nil(list *exps)
{
	node *m;

	for (m = exps->h; m; m = m->next) {
		sql_exp *e = m->data;

		set_has_nil(e);
	}
}

list *
rel_projections(mvc *sql, sql_rel *rel, const char *tname, int settname, int intern )
{
	int label = sql->label;
	list *rexps, *exps ;

	if (!rel || (is_subquery(rel) && is_project(rel->op)))
		return new_exp_list(sql->sa);

	switch(rel->op) {
	case op_join:
	case op_left:
	case op_right:
	case op_full:
	case op_apply:
		exps = rel_projections(sql, rel->l, tname, settname, intern );
		if (rel->op == op_full || rel->op == op_right)
			exps_has_nil(exps);
		if (rel->op != op_apply || (rel->flag  == APPLY_LOJ || rel->flag == APPLY_JOIN)) {
			rexps = rel_projections(sql, rel->r, tname, settname, intern );
			if (rel->op == op_full || rel->op == op_left)
				exps_has_nil(rexps);
			exps = list_merge( exps, rexps, (fdup)NULL);
		}
		return exps;
	case op_groupby:
	case op_addition:
	case op_project:
	case op_basetable:
	case op_table:

	case op_union:
	case op_except:
	case op_inter:
		if (rel->exps) {
			node *en;

			exps = new_exp_list(sql->sa);
			for (en = rel->exps->h; en; en = en->next) {
				sql_exp *e = en->data;
				if (intern || !is_intern(e)) {
					append(exps, e = exp_alias_or_copy(sql, tname, exp_name(e), rel, e));
					if (!settname) /* noname use alias */
						exp_setrelname(sql->sa, e, label);

				}
			}
			return exps;
		}
		exps = rel_projections(sql, rel->l, tname, settname, intern );
		if (exps) {
			node *en;
			for (en = exps->h; en; en = en->next) {
				sql_exp *e = en->data;
				e->card = rel->card;
				if (!settname) /* noname use alias */
					exp_setrelname(sql->sa, e, label);
			}
		}
		return exps;
	case op_ddl:
	case op_semi:
	case op_anti:

	case op_select:
	case op_topn:
	case op_sample:
		return rel_projections(sql, rel->l, tname, settname, intern );
	default:
		return NULL;
	}
}

/* find the path to the relation containing the base of the expression
	(e_column), in most cases this means go down the join tree and
	find the base column.
 */
static int
rel_bind_path_(sql_rel *rel, sql_exp *e, list *path )
{
	int found = 0;

	switch (rel->op) {
	case op_join:
	case op_left:
	case op_right:
	case op_full:
	case op_apply:
		/* first right (possible subquery) */
		found = rel_bind_path_(rel->r, e, path);
		if (!found)
			found = rel_bind_path_(rel->l, e, path);
		break;
	case op_semi:
	case op_anti:

	case op_select:
	case op_topn:
	case op_sample:
		found = rel_bind_path_(rel->l, e, path);
		break;

	case op_union:
	case op_inter:
	case op_except:
		if (!rel->exps) {
			found = rel_bind_path_(rel->l, e, path);
			assert(0);
			break;
		}
	case op_groupby:
	case op_addition:
	case op_project:
	case op_table:
	case op_basetable:
		if (!rel->exps)
			break;
		if (!found && e->l && exps_bind_column2(rel->exps, e->l, e->r))
			found = 1;
		if (!found && !e->l && exps_bind_column(rel->exps, e->r, NULL))
			found = 1;
		break;
	case op_insert:
	case op_update:
	case op_delete:
		break;
	case op_ddl:
		break;
	}
	if (found)
		list_prepend(path, rel);
	return found;
}

static list *
rel_bind_path(sql_allocator *sa, sql_rel *rel, sql_exp *e )
{
	list *path = new_rel_list(sa);

	if (e->type == e_convert)
		e = e->l;
	if (e->type == e_column) {
		if (rel) {
			if (!rel_bind_path_(rel, e, path)) {
				/* something is wrong */
				return NULL;
			}
		}
		return path;
	}
	/* default the top relation */
	append(path, rel);
	return path;
}

/* ls is the left expression of the select, rs is a simple atom, e is the
   select expression.
 */
sql_rel *
rel_push_select(mvc *sql, sql_rel *rel, sql_exp *ls, sql_exp *e)
{
	list *l = rel_bind_path(sql->sa, rel, ls);
	node *n;
	sql_rel *lrel = NULL, *p = NULL;

	if (!l || !sql->pushdown) {
		/* expression has no clear parent relation, so filter current
		   with it */
		return rel_select(sql->sa, rel, e);
	}

	for (n = l->h; n; n = n->next ) {
		lrel = n->data;

		if (rel_is_ref(lrel))
			break;

		/* push down as long as the operators allow this */
		if (!is_select(lrel->op) &&
		    !(is_semi(lrel->op) && !rel_is_ref(lrel->l)) &&
		    lrel->op != op_join &&
		    lrel->op != op_left)
			break;
		/* pushing through left head of a left join is allowed */
		if (lrel->op == op_left && (!n->next || lrel->l != n->next->data))
			break;
		p = lrel;
	}
	if (!lrel) 
		return NULL;
	if (p && p->op == op_select && !rel_is_ref(p)) { /* refine old select */
		rel_select_add_exp(sql->sa, p, e);
	} else {
		sql_rel *n = rel_select(sql->sa, lrel, e);

		if (p && p != lrel) {
			assert(p->op == op_join || p->op == op_left || is_semi(p->op));
			if (p->l == lrel) {
				p->l = n;
			} else {
				p->r = n;
			}
		} else {
			if (rel != lrel)
				assert(0);
			rel = n;
		}
	}
	return rel;
}


/* ls and rs are the left and right expression of the join, e is the
   join expression.
 */
sql_rel *
rel_push_join(mvc *sql, sql_rel *rel, sql_exp *ls, sql_exp *rs, sql_exp *rs2, sql_exp *e)
{
	list *l = rel_bind_path(sql->sa, rel, ls);
	list *r = rel_bind_path(sql->sa, rel, rs);
	list *r2 = NULL; 
	node *ln, *rn;
	sql_rel *lrel = NULL, *rrel = NULL, *rrel2 = NULL, *p = NULL;

	if (rs2)
		r2 = rel_bind_path(sql->sa, rel, rs2);
	if (!l || !r || (rs2 && !r2)) 
		return NULL;

	if (!sql->pushdown)
		return rel_push_select(sql, rel, ls, e);

	p = rel;
	if (r2) {
		node *rn2;

		for (ln = l->h, rn = r->h, rn2 = r2->h; ln && rn && rn2; ln = ln->next, rn = rn->next, rn2 = rn2->next ) {
			lrel = ln->data;
			rrel = rn->data;
			rrel2 = rn2->data;
			
			if (rel_is_ref(lrel) || rel_is_ref(rrel) || rel_is_ref(rrel2) || is_processed(lrel) || is_processed(rrel))
				break;

			/* push down as long as the operators allow this
				and the relation is equal.
		 	*/
			if (lrel != rrel || lrel != rrel2 ||
				(!is_select(lrel->op) &&
				 !(is_semi(lrel->op) && !rel_is_ref(lrel->l)) &&
				 lrel->op != op_join &&
				 lrel->op != op_left))
				break;
			/* pushing through left head of a left join is allowed */
			if (lrel->op == op_left && (!ln->next || lrel->l != ln->next->data))
				break;
			p = lrel;
		}
	} else {
		for (ln = l->h, rn = r->h; ln && rn; ln = ln->next, rn = rn->next ) {
			lrel = ln->data;
			rrel = rn->data;
			
			if (rel_is_ref(lrel) || rel_is_ref(rrel) || is_processed(lrel) || is_processed(rrel))
				break;

			/* push down as long as the operators allow this
				and the relation is equal.
		 	*/
			if (lrel != rrel ||
				(!is_select(lrel->op) &&
				 !(is_semi(lrel->op) && !rel_is_ref(lrel->l)) &&
				 lrel->op != op_join &&
				 lrel->op != op_left))
				break;
			/* pushing through left head of a left join is allowed */
			if (lrel->op == op_left && (!ln->next || lrel->l != ln->next->data))
				break;
			p = lrel;
		}
	}
	if (!lrel || !rrel || (r2 && !rrel2))
		return NULL;

	/* filter on columns of this relation */
	if ((lrel == rrel && (!r2 || lrel == rrel2) && lrel->op != op_join) || rel_is_ref(p)) {
		if (lrel->op == op_select && !rel_is_ref(lrel)) {
			rel_select_add_exp(sql->sa, lrel, e);
		} else if (p && p->op == op_select && !rel_is_ref(p)) {
			rel_select_add_exp(sql->sa, p, e);
		} else {
			sql_rel *n = rel_select(sql->sa, lrel, e);

			if (p && p != lrel) {
				if (p->l == lrel)
					p->l = n;
				else
					p->r = n;
			} else {
				rel = n;
			}
		}
		return rel;
	}

	rel_join_add_exp( sql->sa, p, e);
	return rel;
}

sql_rel *
rel_or(mvc *sql, sql_rel *l, sql_rel *r, list *oexps, list *lexps, list *rexps)
{
	sql_rel *rel, *ll = l->l, *rl = r->l;

	assert(!lexps || l == r);
	if (l == r && lexps) { /* merge both lists */
		sql_exp *e = exp_or(sql->sa, lexps, rexps);
		list *nl = oexps?oexps:new_exp_list(sql->sa); 
		
		rel_destroy(r);
		append(nl, e);
		if (is_outerjoin(l->op) && is_processed(l)) 
			l = rel_select(sql->sa, l, NULL);
		l->exps = nl;
		return l;
	}

	/* favor or expressions over union */
	if (l->op == r->op && l->op == op_select &&
	    ll == rl && !rel_is_ref(l) && !rel_is_ref(r)) {
		sql_exp *e = exp_or(sql->sa, l->exps, r->exps);
		list *nl = new_exp_list(sql->sa); 
		
		rel_destroy(r);
		append(nl, e);
		l->exps = nl;

		/* merge and expressions */
		ll = l->l;
		while (ll && ll->op == op_select && !rel_is_ref(ll)) {
			list_merge(l->exps, ll->exps, (fdup)NULL);
			l->l = ll->l;
			ll->l = NULL;
			rel_destroy(ll);
			ll = l->l;
		}
		return l;
	}

	l = rel_project(sql->sa, l, rel_projections(sql, l, NULL, 1, 1));
	r = rel_project(sql->sa, r, rel_projections(sql, r, NULL, 1, 1));
	set_processed(l);
	set_processed(r);
	rel = rel_setop(sql->sa, l, r, op_union);
	rel->exps = rel_projections(sql, rel, NULL, 1, 1);
	rel = rel_distinct(rel);
	if (exps_card(l->exps) <= CARD_AGGR &&
	    exps_card(r->exps) <= CARD_AGGR)
	{
		rel->card = exps_card(l->exps);
		exps_fix_card( rel->exps, rel->card);
	}
	return rel;
}

sql_table *
rel_ddl_table_get(sql_rel *r)
{
	if (r->flag == DDL_ALTER_TABLE || r->flag == DDL_CREATE_TABLE || r->flag == DDL_CREATE_VIEW) {
		sql_exp *e = r->exps->t->data;
		atom *a = e->l;

		return a->data.val.pval;
	}
	return NULL;
}

static sql_exp *
exps_find_identity(list *exps) 
{
	node *n;

	for (n=exps->h; n; n = n->next) {
		sql_exp *e = n->data;

		if (is_identity(e, NULL))
			return e;
	}
	return NULL;
}

static sql_rel *
_rel_add_identity(mvc *sql, sql_rel *rel, sql_exp **exp)
{
	list *exps = rel_projections(sql, rel, NULL, 1, 1);
	sql_exp *e;

	if (list_length(exps) == 0) {
		*exp = NULL;
		return rel;
	}
	rel = rel_project(sql->sa, rel, rel_projections(sql, rel, NULL, 1, 1));
	e = rel->exps->h->data;
	e = exp_column(sql->sa, exp_relname(e), exp_name(e), exp_subtype(e), rel->card, has_nil(e), is_intern(e));
	e = exp_unop(sql->sa, e, sql_bind_func(sql->sa, NULL, "identity", exp_subtype(e), NULL, F_FUNC));
	e->p = prop_create(sql->sa, PROP_HASHCOL, e->p);
	*exp = exp_label(sql->sa, e, ++sql->label);
	rel_project_add_exp(sql, rel, e);
	return rel;
}

sql_rel *
rel_add_identity(mvc *sql, sql_rel *rel, sql_exp **exp)
{
	if (rel && is_project(rel->op) && (*exp = exps_find_identity(rel->exps)) != NULL) 
		return rel;
	return _rel_add_identity(sql, rel, exp);
}
