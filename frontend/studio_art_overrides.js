const STUDIO_ART_HTTP_VERSION='v5';
studioArtUrl=function(id){return `/api/artwork/studios/${encodeURIComponent(id)}?v=${STUDIO_ART_HTTP_VERSION}`;};
