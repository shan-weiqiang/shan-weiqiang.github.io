---
# Feel free to add content and custom Front Matter to this file.
# To modify the layout, see https://jekyllrb.com/docs/themes/#overriding-theme-defaults

layout: default
title: Archive
---

{% assign current_year = '' %}
<ul>
  {% for post in site.posts %}
    {% capture post_year %}{{ post.date | date: "%Y" }}{% endcapture %}
    {% if post_year != current_year %}
      <h2>{{ post_year }}</h2>
      {% assign current_year = post_year %}
    {% endif %}
    <li>
      <a href="{{ post.url }}">{{ post.title }}</a> - {{ post.date | date: "%B %d, %Y" }}
    </li>
  {% endfor %}
</ul>
