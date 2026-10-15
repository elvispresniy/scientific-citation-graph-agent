"""Diagnostic transformations with explicit expectations, not a semantic gold test."""
import json
from pathlib import Path
from measure_terms import Doc, query_features, scores, METHODS, split_references, lemma_word, stem_word
from section_text import split_html,split_pdf
ROOT=Path(__file__).resolve().parent
IDF={'__unseen__':1}
CASES=[
 ('same_words','Одинаковые слова','Delaunay triangulation','Delaunay triangulation generates meshes.',
  'Ожидаем полное словарное совпадение.'),
 ('plural','Только множественное число','Delaunay triangulation','Delaunay triangulations generate meshes.',
  'Метрика с нормализацией должна убрать различие triangulation/triangulations.'),
 ('abbreviation','Сокращение вместо полного названия','deep RL','Deep reinforcement learning trains policies.',
  'Раскрытие RL требует явного словаря; совпадение букв не должно выдаваться за распознавание сокращения.'),
 ('dispersed','Слова далеко друг от друга','graph learning','graph '+('protein '*45)+'learning',
  'Отдельные слова совпадают, но словосочетание и окна 10/30 — нет; окно 100 уже допускает такое расстояние.'),
 ('stemming_collision','Общая основа у разных слов','organ','organize',
  'Organ — орган, organize — организовывать. Стемминг может ошибочно слить эти слова.'),
 ('negation','Слова совпали, смысл требования изменён','increase efficiency','efficiency does not increase',
  'Высокое совпадение слов не доказывает, что статья удовлетворяет требованию.'),
 ('irrelevant_added','Добавлен посторонний словарь','Delaunay triangulation',
  'Delaunay triangulation generates meshes. protein quantum galaxy budget soil culture antenna metabolism politics computer',
  'Покрытие запроса должно сохраниться; симметричные меры могут упасть из-за дополнительного словаря.'),
]
rows=[]
for key,name,q,d,expected in CASES:
 values,_=scores(query_features([q]),Doc(d),IDF)
 rows.append({'case':key,'name':name,'query':q,'document':d,'expected':expected,'scores':values})
b={x['case']:x['scores'] for x in rows}
assert b['same_words']['words_exact']==1
assert b['plural']['words_exact']<b['plural']['words_lemma']==1
assert b['abbreviation']['words_exact']<b['abbreviation']['words_alias']==1
assert b['dispersed']['words_lemma']==1 and b['dispersed']['phrases_lemma']==0 and b['dispersed']['local_terms']==0
assert b['dispersed']['local_terms_10']==0 and b['dispersed']['local_terms_100']==1
assert b['stemming_collision']['words_exact']==0 and b['stemming_collision']['words_lemma']==0 and b['stemming_collision']['words_stem']==1
assert b['irrelevant_added']['words_lemma']==b['same_words']['words_lemma']
assert b['irrelevant_added']['jaccard']<b['same_words']['jaccard']
assert b['irrelevant_added']['idf_cosine']<b['same_words']['idf_cosine']
# Bibliography removal must preserve appendices that occur after it.
sample='Title\nMain body.\nREFERENCES\n[1] Example citation.\nAppendix A\nProof details.\n'
body,refs,info=split_references(sample)
assert 'Example citation' not in body and 'Proof details' in body
assert 'Example citation' in refs and 'Proof details' not in refs
html='''<html><article class="ltx_document"><section id="S1"><h2>1 Introduction</h2><p>Own motivation.</p></section><section id="S2"><h2>2 Related Work</h2><p>External method.</p><section><h3>2.1 Earlier experiments</h3><p>External results.</p></section></section><section><h2>3 Methods</h2><p>Own algorithm.</p></section><div class="ltx_bibliography">External title.</div><section><h2>Appendix A</h2><p>Own proof.</p></section></article></html>'''
_,strict,rw=split_html(html)
assert rw['status']=='removed' and len(rw['sections'])==1
assert 'External' not in strict and all(x in strict for x in ['Own motivation','Own algorithm','Own proof'])
pdf='1 Introduction\nOwn motivation.\n2 Related Work\nExternal results.\n1\nhttp://footnote.example\n2.1 Earlier methods\nExternal detail.\n3 Methods\nOwn algorithm.\nAppendix A\nOwn proof.'
strict,rw=split_pdf(pdf)
assert rw['status']=='removed' and 'External' not in strict and 'Own algorithm' in strict and 'Own proof' in strict
strict,rw=split_pdf('1 Introduction\nWe compare related work on graphs.\n2 Methods\nOwn algorithm.')
assert rw['status']=='no_explicit_section' and 'related work' in strict
_,strict,rw=split_html('<article class="ltx_document"><section><h2>Introduction and Related Work</h2><p>Mixed discussion.</p></section><section><h2>Methods</h2><p>Own algorithm.</p></section></article>')
assert rw['sections'][0]['mixed_heading'] and 'Mixed discussion' not in strict and 'Own algorithm' in strict
(ROOT/'metric-behavior-checks.json').write_text(json.dumps({'status':'passed','purpose':'diagnostic controls, not validation against independent human labels','cases':rows},ensure_ascii=False,indent=2)+'\n')
print('Passed',len(rows),'metric behavior controls; bibliography/Related Work removal, nested sections, mixed headings, prose mentions, footnotes and appendix preservation.')
