---
# Feel free to add content and custom Front Matter to this file.
# To modify the layout, see https://jekyllrb.com/docs/themes/#overriding-theme-defaults

layout: default
title: Archive
wide_layout: true
---

<div class="home-with-tags">
  <section class="home-posts" aria-label="Posts by year">
    {% assign current_year = '' %}
    <ul>
      {% for post in site.posts %}
        {% capture post_year %}{{ post.date | date: "%Y" }}{% endcapture %}
        {% if post_year != current_year %}
          <h2>{{ post_year }}</h2>
          {% assign current_year = post_year %}
        {% endif %}
        <li>
          <a href="{{ post.url | relative_url }}">{{ post.title }}</a> - {{ post.date | date: "%B %d, %Y" }}
        </li>
      {% endfor %}
    </ul>
  </section>

  <aside class="tag-sidebar" aria-labelledby="tag-sidebar-heading">
    <h2 id="tag-sidebar-heading">Tags</h2>
    {%- capture tag_sort_keys -%}
      {%- for tag in site.tags -%}
        {%- assign tag_post_count = tag[1] | size -%}
        {%- if tag_post_count < 10 -%}00{%- elsif tag_post_count < 100 -%}0{%- endif -%}{{ tag_post_count }}::{{ tag[0] }}{%- unless forloop.last -%},{%- endunless -%}
      {%- endfor -%}
    {%- endcapture -%}
    {% assign sorted_tags = tag_sort_keys | split: ',' | sort | reverse %}
    <ul class="tag-count-list">
      {% for tag_sort_key in sorted_tags %}
        {% assign tag_sort_parts = tag_sort_key | split: '::' %}
        {% assign tag_name = tag_sort_parts[1] %}
        {% assign tagged_posts = site.tags[tag_name] %}
        <li>
          <a href="{{ '/tags/' | relative_url }}#{{ tag_name | slugify }}">{{ tag_name | escape }}</a>
          <span class="tag-count" aria-label="{{ tagged_posts | size }} posts">{{ tagged_posts | size }}</span>
        </li>
      {% endfor %}
    </ul>
  </aside>
</div>
